"""Bounded computation without database credentials or a blocking result pipe.

The supervisor owns the database lease. Its child receives a private JSON snapshot,
publishes a private atomic JSON result, and exits. Only the supervisor may publish to DB.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


DEFAULT_TIMEOUT_SECONDS = 900
MAX_TIMEOUT_SECONDS = 3600
MAX_RESULT_BYTES = 128 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


class CalculationTimeout(Exception):
    pass


class CalculationCancelled(Exception):
    pass


class CalculationFailed(Exception):
    def __init__(self, code='JOB_CALCULATION_FAILED'):
        self.code = code
        super().__init__(code)


def load_timeout(environ=None):
    env = os.environ if environ is None else environ
    value = env.get('WORKER_CALCULATION_TIMEOUT_SECONDS', str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = int(value)
        if str(timeout) != value or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('WORKER_CALCULATION_TIMEOUT_SECONDS must be an integer from 1 to 3600') from None
    return timeout


def calculate_snapshot(payload, snapshot, kind, *, forecast_fn=None, procurement_fn=None):
    # Imported in the calculation child, never a database connection or API app.
    if forecast_fn is None or procurement_fn is None:
        from apps.api.engine import forecast, procurement
        forecast_fn = forecast_fn or forecast
        procurement_fn = procurement_fn or procurement
    context = snapshot.get('execution_context')
    context_argument = {'execution_context': context} if context is not None else {}
    if kind == 'forecast':
        result = forecast_fn(snapshot['sales'], payload['branch_id'], payload['origin'], payload['model'], **context_argument)
        names = {r['meal_id']: r['meal_name'] for r in snapshot.get('meals', [])}
        for item in result['predictions']:
            item['meal_name'] = names.get(str(item['meal_id']), str(item['meal_id']))
    else:
        result = procurement_fn(snapshot['forecast_result'], snapshot['ingredients'], snapshot['recipes'],
            snapshot['inventory_lots'], snapshot['supplier_offers'], snapshot['suppliers'],
            payload['branch_id'], snapshot['forecast_result']['target_date'],
            payload['budget'], payload['strategy'], **context_argument)
        result['recipe_versions'] = sorted({r['recipe_version'] for r in snapshot['recipes']})
        ingredients = {str(r['ingredient_id']): r['ingredient_name'] for r in snapshot['ingredients']}
        suppliers = {str(r['supplier_id']): r['supplier_name'] for r in snapshot['suppliers']}
        for item in result['requirements'] + result['lines']:
            item['ingredient_name'] = ingredients.get(str(item['ingredient_id']), str(item['ingredient_id']))
            if 'supplier_id' in item:
                item['supplier_name'] = suppliers.get(str(item['supplier_id']), str(item['supplier_id']))
    result['input_snapshot_sha256'] = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    expected_origin = context['data_origin'] if context is not None else 'SYNTHETIC'
    if result.get('data_origin', expected_origin) != expected_origin:
        raise ValueError('Conflicting calculation origin')
    result.setdefault('data_origin', expected_origin)
    if context is not None:
        if result.get('execution_context', context) != context:
            raise ValueError('Conflicting calculation context')
        result.setdefault('execution_context', deepcopy(context))
    result['input_lineage'] = deepcopy(snapshot.get('input_lineage'))
    return result


def child_environment():
    # A fresh interpreter needs OS/runtime paths, not API settings or inherited secrets.
    allowed = {'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'TEMP', 'TMP', 'TMPDIR', 'PATH',
               'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', LOKY_MAX_CPU_COUNT='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    return env


def _write_json(path, value):
    # mkdtemp is owner-only on POSIX; exclusive files are also owner read/write.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _stop_child(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    if process.stdin is not None:
        process.stdin.close()


class _ClaimMonitor:
    """A blocked DB check must not prevent enforcing the CPU deadline."""
    def __init__(self, check):
        self.stop = threading.Event()
        self.cancelled = False
        self.error = None

        def observe():
            while not self.stop.is_set():
                try:
                    if not check():
                        self.cancelled = True
                        return
                except Exception as exc:
                    self.error = exc
                    return
                self.stop.wait(0.5)
        self.thread = threading.Thread(target=observe, name='asboljam-claim-monitor', daemon=True)

    def check(self):
        if self.error is not None:
            raise self.error
        if self.cancelled:
            raise CalculationCancelled()


def run_calculation(payload, snapshot, kind, *, claim_active, timeout_seconds=None):
    timeout = load_timeout() if timeout_seconds is None else timeout_seconds
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise ValueError('Invalid calculation timeout')
    with tempfile.TemporaryDirectory(prefix='asboljam-calculation-') as directory:
        source, target = Path(directory) / 'input.json', Path(directory) / 'result.json'
        _write_json(source, {'payload': payload, 'snapshot': snapshot, 'kind': kind})
        command = [sys.executable, '-m', 'apps.worker.calculation_process', '--input', str(source), '--output', str(target)]
        process = subprocess.Popen(command, cwd=ROOT, env=child_environment(), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            start_new_session=os.name != 'nt',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        started = time.monotonic()
        monitor = _ClaimMonitor(claim_active)
        try:
            monitor.thread.start()
            while True:
                monitor.check()
                if time.monotonic() - started >= timeout:
                    raise CalculationTimeout()
                if process.poll() is not None:
                    break
                time.sleep(min(0.1, timeout))
            monitor.check()
            if process.returncode != 0 or not target.is_file() or target.stat().st_size > MAX_RESULT_BYTES:
                raise CalculationFailed()
            try:
                message = json.loads(target.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise CalculationFailed() from None
            if not isinstance(message, dict) or set(message) != {'result', 'error'}:
                raise CalculationFailed()
            if message['error'] in {'JOB_INPUT_INVALID', 'JOB_CALCULATION_FAILED'}:
                raise CalculationFailed(message['error'])
            if message['error'] is not None or not isinstance(message['result'], dict):
                raise CalculationFailed()
            return message['result']
        finally:
            monitor.stop.set()
            _stop_child(process)
            if monitor.thread.ident is not None:
                monitor.thread.join(timeout=0.2)


def _exit_if_parent_dies():
    # The supervisor holds this pipe open without sending data. OS closes it even
    # after SIGKILL/TerminateProcess; exit bypasses a stuck native computation.
    try:
        # Windows CRT locks the descriptor during a blocking read, which can also
        # block library subprocess setup (e.g. platform metadata). Python 3.13
        # supports nonblocking anonymous pipes on Windows as well as POSIX.
        descriptor = sys.stdin.fileno()
        os.set_blocking(descriptor, False)
        while True:
            try:
                if not os.read(descriptor, 1):
                    break
            except BlockingIOError:
                time.sleep(0.1)
    finally:
        os._exit(91)


def child_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    threading.Thread(target=_exit_if_parent_dies, name='asboljam-parent-watch', daemon=True).start()
    try:
        source = json.loads(Path(args.input).read_text(encoding='utf-8'))
        result = calculate_snapshot(source['payload'], source['snapshot'], source['kind'])
        response = {'result': result, 'error': None}
    except Exception as exc:
        response = {'result': None, 'error': 'JOB_INPUT_INVALID' if isinstance(exc, ValueError) else 'JOB_CALCULATION_FAILED'}
    try:
        staging = Path(args.output).with_suffix('.partial')
        _write_json(staging, response)
        os.replace(staging, args.output)
    except Exception:
        # All child streams are discarded too: no values or traceback leave the child.
        os._exit(1)
    # Windows CRT may hold stdin's descriptor lock while the watchdog reads it.
    # All JSON handles are closed now; avoid interpreter teardown closing that
    # descriptor and waiting forever on the still-live supervisor's pipe.
    os._exit(0)


if __name__ == '__main__':
    child_main()
