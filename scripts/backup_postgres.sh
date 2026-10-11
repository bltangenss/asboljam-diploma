#!/usr/bin/env bash
# Verified PostgreSQL backup for the Compose deployment (docker-compose.yml + infra/compose.prod.yml).
#
# Writes backups/asboljam-<UTC>.dump (pg_dump custom format) and a .sha256 file, checks that
# pg_restore can read the archive, never overwrites, and keeps files private (umask 077).
# Old backups are deleted only when BACKUP_RETENTION_DAYS is set explicitly.
# A restore drill into a NEW database is described in docs/commercial/INSTALL_UPDATE_BACKUP_RU.md.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
env_file="${ENV_FILE:-.env}"
compose_files=(-f docker-compose.yml -f "${COMPOSE_OVERLAY:-infra/compose.prod.yml}")
compose=(docker compose --env-file "$env_file" "${compose_files[@]}")
backup_dir="${BACKUP_DIR:-backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/asboljam-$stamp.dump"
# Validate options before any work so a typo cannot leave an extra backup behind.
if [[ -n "${BACKUP_RETENTION_DAYS:-}" && ! "$BACKUP_RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]]; then
  echo "BACKUP_RETENTION_DAYS must be a positive integer" >&2
  exit 1
fi

mkdir -p "$backup_dir"
if [[ -e "$target" || -e "$target.partial" ]]; then
  echo "Backup $target already exists; nothing was overwritten." >&2
  exit 1
fi
cleanup() { rm -f -- "$target.partial"; }
trap cleanup ERR
"${compose[@]}" exec -T postgres pg_dump -U asboljam -d asboljam --format=custom > "$target.partial"
# The archive must be readable by pg_restore before it is accepted.
entries="$("${compose[@]}" exec -T postgres pg_restore --list < "$target.partial" | grep -c ' TABLE DATA ' || true)"
if [[ "$entries" -lt 1 ]]; then
  echo "Backup archive has no table data; rejected." >&2
  exit 1
fi
mv -- "$target.partial" "$target"
trap - ERR
(cd "$backup_dir" && sha256sum "$(basename "$target")" > "$(basename "$target").sha256")
echo "Backup written: $target ($(wc -c < "$target") bytes, $entries table data entries)"
echo "SHA256: $(cut -d' ' -f1 "$target.sha256")"

if [[ -n "${BACKUP_RETENTION_DAYS:-}" ]]; then
  find "$backup_dir" -maxdepth 1 -type f \( -name 'asboljam-*.dump' -o -name 'asboljam-*.dump.sha256' \) \
    -mtime +"$BACKUP_RETENTION_DAYS" -print -delete
fi
echo "Copy the backup off the server; it contains business data and password hashes."
