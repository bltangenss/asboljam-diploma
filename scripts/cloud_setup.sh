#!/usr/bin/env bash
# Dependency setup for a Linux cloud checkout. No source/database deletion or seeding.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
python_bin="${ASBOLJAM_PYTHON:-python3.13}"
if ! command -v "$python_bin" >/dev/null 2>&1; then python_bin=python3; fi
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3,13), "Select Python 3.13 in the cloud environment"; print("Python",sys.version.split()[0])'
node -e 'if(Number(process.versions.node.split(".")[0])!==24) throw Error("Select Node.js 24 in the cloud environment"); console.log("Node",process.versions.node)'
if [[ ! -x .venv/bin/python ]]; then
  if [[ -e .venv ]]; then
    printf '%s\n' 'Existing .venv is not a Linux virtual environment; preserve it and choose a clean Linux checkout.' >&2
    exit 1
  fi
  "$python_bin" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock
npm ci --no-audit --no-fund
if [[ "${ASBOLJAM_SETUP_MOBILE:-1}" == 1 ]]; then
  (cd apps/mobile && npm ci --no-audit --no-fund)
fi
if [[ "${ASBOLJAM_INSTALL_BROWSER:-1}" == 1 ]]; then
  if [[ "${ASBOLJAM_BROWSER_SYSTEM_DEPS:-1}" == 1 ]]; then
    npx --no-install playwright install --with-deps chromium
  else
    npx --no-install playwright install chromium
  fi
fi
printf '%s\n' 'Dependencies installed. Next: bash scripts/cloud_verify.sh' 'No OpenAI API key is needed by this application. No cloud connection or deployment was created by this script.'
