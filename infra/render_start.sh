#!/bin/sh
# Render free plan has no background workers, so one container runs both processes:
# the database-queue worker in a restart loop and the API as the main process.
# Render health-checks the API; a crashed worker is restarted after a short pause.
set -eu

(
  while true; do
    python -m apps.worker.main || echo '{"event":"worker.exited","restart_in_seconds":5}'
    sleep 5
  done
) &

exec python -m uvicorn apps.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
