"""Only launched by process tests; artificial computations, never production flags."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.worker import calculation_process as calculation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', required=True)
    parser.add_argument('--marker', required=True)
    parser.add_argument('--input')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.mode == 'supervisor':
        original = subprocess.Popen

        def launch(command, **kwargs):
            return original([sys.executable, str(Path(__file__).resolve()), '--mode', 'hang',
                '--marker', args.marker, *command[3:]], **kwargs)
        calculation.subprocess.Popen = launch
        calculation.run_calculation({}, {}, 'forecast', claim_active=lambda: True, timeout_seconds=30)
        return

    def compute(payload, snapshot, kind):
        Path(args.marker).write_text(json.dumps({'pid': os.getpid(), 'directory': str(Path(args.input).parent)}), encoding='utf-8')
        if args.mode == 'hang':
            while True:
                time.sleep(0.1)
        if args.mode == 'large':
            return {'data': 'z' * (3 * 1024 * 1024)}
        if args.mode == 'error':
            print('private-fixture-raw-row', flush=True)
            print('private-fixture-raw-row', file=sys.stderr, flush=True)
            raise RuntimeError('private-fixture-raw-row')
        if args.mode == 'environment':
            return {'secret_inherited': any(key in os.environ for key in
                ('DATABASE_URL', 'DEMO_PASSWORD', 'PRIVATE_FIXTURE_SECRET', 'ASBOLJAM_SECURITY_TEST_DATABASE_URL'))}
        if args.mode == 'wait-valid':
            time.sleep(1)
        return calculation.calculate_snapshot_original(payload, snapshot, kind,
            forecast_fn=lambda *args, **kwargs: dict(branch_id='1', target_date='2026-01-01',
                data_origin='SYNTHETIC', predictions=[dict(meal_id='1', point_forecast=2)]),
            procurement_fn=lambda *args, **kwargs: {})

    calculation.calculate_snapshot_original = calculation.calculate_snapshot
    calculation.calculate_snapshot = compute
    sys.argv = [sys.argv[0], '--input', args.input, '--output', args.output]
    calculation.child_main()


if __name__ == '__main__':
    main()
