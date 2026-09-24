"""Package a clean, committed source tree, verify every entry, exclude private state."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIRS = {'.git', '.cache', '.venv', 'venv', 'node_modules', '__pycache__', '.expo', '.test-build', 'dist', 'build', 'coverage', 'test-results', 'playwright-report', 'backups', 'releases'}
FORBIDDEN_SUFFIXES = {'.pem', '.key', '.pfx', '.p12', '.sqlite', '.sqlite3', '.db', '.pyc', '.log', '.zip', '.apk', '.aab', '.ipa', '.apks'}
REQUIRED = {'README.md', 'README_KK.md', 'FINAL_REPORT.md', 'PROGRESS.md', 'DECISIONS.md', 'CLOUD_HANDOFF.md', 'AGENTS.md', '.env.example', 'docker-compose.yml', 'requirements.lock', 'package-lock.json', 'apps/mobile/package-lock.json', 'contracts/openapi.json', 'contracts/data_manifest.json', 'database/migrate.py', 'apps/api/main.py', 'apps/worker/main.py', 'apps/web/src/App.tsx', 'apps/mobile/App.tsx', 'tests/test_api.py', 'tests/test_engine.py', 'tests/e2e/workflow.spec.ts', 'docs/SOURCE_REVIEW_RU.md', 'data/raw/daily_sales.csv'}

def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)

def allowed(name: str) -> bool:
    p = PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts and not (set(p.parts) & FORBIDDEN_DIRS)
            and p.suffix.lower() not in FORBIDDEN_SUFFIXES
            and not (p.name.startswith('.env') and p.name != '.env.example')
            and '.sqlite-' not in p.name)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='releases/AsBoljam_Final.zip')
    args = parser.parse_args()
    target = (ROOT / args.output).resolve()
    if not target.is_relative_to(ROOT / 'releases') or target.suffix.lower() != '.zip':
        raise SystemExit('Output must be a ZIP under this project releases directory.')
    if target.exists():
        raise SystemExit('Output exists; choose a new filename. Existing releases are preserved.')
    if git('status', '--porcelain').strip():
        raise SystemExit('Commit reviewed source and evidence first; the source tree must be clean.')
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_secrets.py'), '--no-report'], cwd=ROOT, check=True)
    names = sorted(n for n in git('ls-files', '-z').decode('utf-8').split('\0') if n)
    missing = REQUIRED - set(names)
    forbidden = [n for n in names if not allowed(n)]
    if missing or forbidden:
        raise SystemExit(json.dumps({'missing_required': sorted(missing), 'forbidden_files': forbidden}))
    checksums: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for name in names:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or not path.is_file():
            raise SystemExit('Unsafe/nonregular source path: ' + name)
        payload = path.read_bytes()
        checksums[name] = hashlib.sha256(payload).hexdigest()
        sizes[name] = len(payload)
    manifest = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'source_commit': git('rev-parse', 'HEAD').decode().strip(), 'files': checksums, 'sizes_bytes': sizes, 'note': 'Source release. Test evidence and explicit unverified scope are in FINAL_REPORT.md. Credentials and installed dependencies are excluded.'}
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            archive.write(ROOT / name, 'AsBoljam/' + name)
        archive.writestr('AsBoljam/RELEASE_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(target) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise SystemExit('ZIP CRC validation failed: ' + corrupt)
        if len(archive.namelist()) != len(names) + 1:
            raise SystemExit('Unexpected ZIP entry count.')
        for name, digest in checksums.items():
            if hashlib.sha256(archive.read('AsBoljam/' + name)).hexdigest() != digest:
                raise SystemExit('Archive checksum mismatch: ' + name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(target.relative_to(ROOT)), 'source_commit': manifest['source_commit'], 'files': len(names), 'bytes': target.stat().st_size, 'sha256': digest, 'crc_and_all_file_hashes': 'PASS'}, indent=2))

if __name__ == '__main__':
    main()
