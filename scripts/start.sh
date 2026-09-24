#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
# Import only KEY=VALUE assignments; never execute .env contents.
if [[ -f .env ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      name="${BASH_REMATCH[1]}"; value="${BASH_REMATCH[2]}"
      value="${value#\"}"; value="${value%\"}"; value="${value#\'}"; value="${value%\'}"
      if [[ -n "$value" && -z "${!name:-}" ]]; then export "$name=$value"; fi
    fi
  done < .env
fi
if [[ "${1:-}" == '--install' ]]; then
  [[ -x .venv/bin/python ]] || python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.lock
  npm ci
fi
python_bin="$(command -v python3)"
[[ ! -x .venv/bin/python ]] || python_bin="$project_root/.venv/bin/python"
[[ -f node_modules/vite/bin/vite.js ]] || { echo 'Run bash scripts/start.sh --install first.'; exit 1; }
"$python_bin" -c 'import socket; sockets=[socket.socket() for _ in range(2)]; [s.bind(("127.0.0.1",p)) for s,p in zip(sockets,(8000,3000))]; [s.close() for s in sockets]'
"$python_bin" database/migrate.py
"$python_bin" scripts/seed_demo.py
mkdir -p .cache/logs
: > .cache/processes.pid
pids=()
cleanup_failed_start() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup_failed_start ERR
nohup "$python_bin" -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 >.cache/logs/api.log 2>.cache/logs/api.err.log < /dev/null &
pids+=("$!")
nohup "$python_bin" -m apps.worker.main >.cache/logs/worker.log 2>.cache/logs/worker.err.log < /dev/null &
pids+=("$!")
nohup node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 >.cache/logs/web.log 2>.cache/logs/web.err.log < /dev/null &
pids+=("$!")
for pid in "${pids[@]}"; do printf '%s|%s\n' "$pid" "$(ps -p "$pid" -o lstart=)" >> .cache/processes.pid; done
sleep 2
for pid in "${pids[@]}"; do kill -0 "$pid"; done
trap - ERR
printf '%s\n' 'AsBoljam started: http://localhost:3000' 'Logs: .cache/logs. Stop with bash scripts/stop.sh.'
