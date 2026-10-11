#!/usr/bin/env bash
# Run on Linux after cloud_setup.sh. Only a fresh .cache database is mutated.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
python_bin="$project_root/.venv/bin/python"
[[ -x "$python_bin" ]] || { printf '%s\n' 'Run bash scripts/cloud_setup.sh first.' >&2; exit 1; }
mkdir -p .cache/cloud
run_dir="$(mktemp -d "$project_root/.cache/cloud/verify.XXXXXXXX")"
export DATABASE_URL="sqlite:///$run_dir/runtime.sqlite"
export ALLOWED_ORIGINS='http://localhost:3000,http://127.0.0.1:3000'
export COOKIE_SECURE=false
export LOKY_MAX_CPU_COUNT=1
export PLAYWRIGHT_CHANNEL="${PLAYWRIGHT_CHANNEL:-chromium}"
export PYTHONUNBUFFERED=1
api_pid=''; worker_pid=''; web_pid=''
cleanup() {
  local task_pid
  for task_pid in "$web_pid" "$worker_pid" "$api_pid"; do
    if [[ -n "$task_pid" ]]; then kill "$task_pid" 2>/dev/null || true; fi
  done
  for task_pid in "$web_pid" "$worker_pid" "$api_pid"; do
    if [[ -n "$task_pid" ]]; then wait "$task_pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
trap 'exit 130' INT TERM
printf 'Verification evidence directory: %s\n' "$run_dir"
"$python_bin" -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
npm run build
if [[ "${ASBOLJAM_VERIFY_MOBILE:-1}" == 1 ]]; then
  (cd apps/mobile && npm run typecheck && npm test)
fi
if [[ "${ASBOLJAM_VERIFY_RESEARCH:-1}" == 1 ]]; then
  "$python_bin" -X utf8 scripts/run_research.py --output "$run_dir/research"
fi
if [[ "${ASBOLJAM_VERIFY_E2E:-1}" == 1 ]]; then
  "$python_bin" -c 'import socket; probes=[socket.socket() for _ in range(2)]; [s.bind(("127.0.0.1",p)) for s,p in zip(probes,(8000,3000))]; [s.close() for s in probes]'
  "$python_bin" -X utf8 scripts/prepare_e2e.py
  "$python_bin" -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --no-access-log >"$run_dir/api.log" 2>&1 &
  api_pid=$!
  "$python_bin" -m apps.worker.main >"$run_dir/worker.log" 2>&1 &
  worker_pid=$!
  node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 --strictPort >"$run_dir/web.log" 2>&1 &
  web_pid=$!
  "$python_bin" - <<'PY'
import time
from urllib.request import urlopen
for url in ('http://127.0.0.1:8000/api/v1/ready', 'http://127.0.0.1:3000'):
    deadline = time.monotonic() + 60
    while True:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        if time.monotonic() >= deadline:
            raise SystemExit('Server readiness failed; inspect the verification log directory')
        time.sleep(1)
PY
  npm run test:e2e
fi
"$python_bin" -X utf8 scripts/check_secrets.py
printf '%s\n' 'Enabled verification checks completed successfully.' 'Disabled checks, Docker/PostgreSQL, device builds and cloud connection are not certified by this script.'
