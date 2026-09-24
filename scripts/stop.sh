#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
[[ -f .cache/processes.pid ]] || { echo 'No saved AsBoljam processes.'; exit 0; }
while IFS='|' read -r pid started; do
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  actual="$(ps -p "$pid" -o lstart= 2>/dev/null || true)"
  if [[ -n "$actual" && "$actual" == "$started" ]]; then kill "$pid"; printf 'Stopped process %s.\n' "$pid"; fi
done < .cache/processes.pid
