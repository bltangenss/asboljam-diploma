"""Package committed Git blobs, or an explicit verified working-tree snapshot."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIRS = {'.git', '.cache', '.venv', 'venv', 'node_modules', '__pycache__', '.expo', '.test-build', 'dist', 'build', 'coverage', 'test-results', 'playwright-report', 'backups', 'releases'}
FORBIDDEN_SUFFIXES = {'.pem', '.key', '.pfx', '.p12', '.jks', '.keystore', '.dump', '.sqlite', '.sqlite3', '.db', '.pyc', '.log', '.zip', '.apk', '.aab', '.ipa', '.apks'}
REQUIRED = {'README.md', 'README_KK.md', 'README_RU.md', 'FINAL_REPORT.md', 'PROGRESS.md', 'DECISIONS.md', 'CLOUD_HANDOFF.md', 'AGENTS.md', '.env.example', 'docker-compose.yml', 'requirements.lock', 'package-lock.json', 'apps/mobile/package-lock.json', 'contracts/openapi.json', 'contracts/data_manifest.json', 'database/migrate.py', 'apps/api/main.py', 'apps/worker/main.py', 'apps/web/src/App.tsx', 'apps/mobile/App.tsx', 'tests/test_api.py', 'tests/test_engine.py', 'tests/e2e/workflow.spec.ts', 'docs/SOURCE_REVIEW_RU.md', 'data/raw/daily_sales.csv', 'data/kz/daily_sales.csv', 'scripts/generate_kz_demo.py'}
MANIFEST_NAME = 'RELEASE_MANIFEST.json'

def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})

def allowed(name: str) -> bool:
    p = PurePosixPath(name)
    lowered = p.name.casefold()
    return (bool(name) and p.as_posix() == name and not p.is_absolute() and '..' not in p.parts
            and not any(ord(char) < 32 or char in '\\:' for char in name)
            and not ({part.casefold() for part in p.parts} & FORBIDDEN_DIRS)
            and p.suffix.lower() not in FORBIDDEN_SUFFIXES
            and not (lowered.startswith('.env') and lowered != '.env.example')
            and not re.search(r'\.(?:sqlite3?|db)-(?:wal|shm|journal)$', lowered)
            and '.sqlite-' not in lowered
            and name.casefold() != MANIFEST_NAME.casefold())


def committed_tree(commit: str) -> list[tuple[str, str, str]]:
    """Read path/mode/object IDs from one immutable tree, never from the index."""
    entries = []
    for record in git('ls-tree', '-r', '-z', '--full-tree', commit).split(b'\0'):
        if not record:
            continue
        metadata, raw_name = record.split(b'\t', 1)
        mode, kind, object_id = metadata.decode('ascii').split()
        name = raw_name.decode('utf-8')
        if kind != 'blob' or mode not in {'100644', '100755'}:
            raise SystemExit('Symlinks, submodules and nonregular committed paths are refused: ' + name)
        entries.append((name, mode, object_id))
    entries.sort()
    names = [name for name, _, _ in entries]
    if len({name.casefold() for name in names}) != len(names):
        raise SystemExit('Case-colliding committed paths are unsafe for a portable source archive.')
    return entries


def committed_blobs(entries: list[tuple[str, str, str]]) -> dict[str, bytes]:
    """Read exact blob bytes in one Git process; no worktree filters or rereads."""
    object_ids = list(dict.fromkeys(object_id for _, _, object_id in entries))
    if not object_ids:
        return {}
    output = subprocess.check_output(['git', 'cat-file', '--batch'], cwd=ROOT,
                                     input=('\n'.join(object_ids) + '\n').encode('ascii'),
                                     env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    position, blobs = 0, {}
    for expected in object_ids:
        line_end = output.find(b'\n', position)
        if line_end < 0:
            raise SystemExit('Incomplete Git blob response.')
        header = output[position:line_end].decode('ascii').split()
        if len(header) != 3 or header[0] != expected or header[1] != 'blob' or not header[2].isdigit():
            raise SystemExit('Unexpected Git blob response.')
        size = int(header[2])
        start, end = line_end + 1, line_end + 1 + size
        if end >= len(output) or output[end:end + 1] != b'\n':
            raise SystemExit('Truncated Git blob response.')
        blobs[expected] = output[start:end]
        position = end + 1
    if position != len(output):
        raise SystemExit('Unexpected trailing Git blob data.')
    return blobs


def working_tree_paths() -> tuple[list[str], list[str]]:
    """Read Git metadata only; never stage, commit, change locks or write refs."""
    names = {name for name in git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0') if name}
    deleted = {name for name in git('ls-files', '--deleted', '-z').decode('utf-8').split('\0') if name}
    return sorted(names - deleted), sorted(deleted)


def check_paths(names: list[str]) -> None:
    missing = REQUIRED - set(names)
    forbidden = [name for name in names if not allowed(name)]
    if missing or forbidden:
        raise SystemExit(json.dumps({'missing_required': sorted(missing), 'forbidden_files': forbidden}))
    if len({name.casefold() for name in names}) != len(names):
        raise SystemExit('Case-colliding paths are unsafe for a portable source archive.')


def read_working_file(name: str) -> tuple[str, bytes]:
    path = ROOT / name
    if path.is_symlink() or path.resolve() != path.absolute() or not path.resolve().is_relative_to(ROOT):
        raise SystemExit('Symlink/junction or escaping working-tree path refused: ' + name)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise SystemExit('Nonregular working-tree source path refused: ' + name)
    payload = path.read_bytes()
    after = path.stat()
    signature = lambda value: (value.st_size, value.st_mtime_ns, value.st_ino, value.st_mode)
    if signature(before) != signature(after) or len(payload) != after.st_size:
        raise SystemExit('Source changed while being read; retry after edits stop: ' + name)
    mode = '100755' if before.st_mode & stat.S_IXUSR else '100644'
    return mode, payload


def snapshot_working_tree() -> tuple[list[tuple[str, str, bytes]], list[str]]:
    names, deleted = working_tree_paths()
    check_paths(names)
    return [(name, *read_working_file(name)) for name in names], deleted


def verify_working_snapshot(files: list[tuple[str, str, bytes]], deleted: list[str]) -> None:
    names_now, deleted_now = working_tree_paths()
    if names_now != [name for name, _, _ in files] or deleted_now != deleted:
        raise SystemExit('Working-tree file list changed during snapshot; retry after edits stop.')
    for name, mode, payload in files:
        current_mode, current = read_working_file(name)
        if current_mode != mode or current != payload:
            raise SystemExit('Working-tree bytes changed during snapshot; retry after edits stop: ' + name)


def scan_snapshot(files: list[tuple[str, str, bytes]]) -> None:
    """Scan the actual archived buffers, including committed bytes hidden by filters."""
    patterns = [
        ('private-key', rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        ('github-token', rb'gh[pousr]_[A-Za-z0-9]{30,}'),
        ('github-fine-grained-token', rb'github_pat_[A-Za-z0-9_]{40,}'),
        ('openai-key', rb'sk-(?:proj-)?[A-Za-z0-9_-]{40,}'),
        ('aws-key', rb'AKIA[0-9A-Z]{16}'),
    ]
    known = []
    for source in ROOT.glob('.env*'):
        if source.name.casefold() == '.env.example' or not source.is_file():
            continue
        for line in source.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                value = value.strip().strip('\'"')
                if re.search(r'PASSWORD|TOKEN|SECRET|API_KEY', key, re.I) and len(value) >= 10:
                    known.append(value.encode('utf-8'))
    credential = ROOT / '.cache/e2e-login.json'
    if credential.exists():
        known.append(json.loads(credential.read_text(encoding='utf-8-sig'))['password'].encode('utf-8'))
    findings = []
    for name, _, payload in files:
        if any(value and value in payload for value in known):
            findings.append({'file': name, 'category': 'known-local-secret'})
        for category, pattern in patterns:
            if re.search(pattern, payload):
                findings.append({'file': name, 'category': category})
    if findings:
        raise SystemExit(json.dumps({'snapshot_secret_findings': findings}))

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='releases/AsBoljam_Final.zip')
    parser.add_argument('--working-tree', action='store_true', help='Explicit fallback: package a verified snapshot with source_commit=null; no Git writes')
    args = parser.parse_args()
    target = (ROOT / args.output).resolve()
    if not target.is_relative_to(ROOT / 'releases') or target.suffix.lower() != '.zip':
        raise SystemExit('Output must be a ZIP under this project releases directory.')
    if target.exists():
        raise SystemExit('Output exists; choose a new filename. Existing releases are preserved.')
    checksum_path = target.with_suffix('.zip.sha256')
    if checksum_path.exists():
        raise SystemExit('Checksum output exists; choose a new filename. Existing release evidence is preserved.')
    if not args.working_tree and git('status', '--porcelain').strip():
        raise SystemExit('Commit reviewed source and evidence first; the source tree must be clean.')
    commit = git('rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_secrets.py'), '--no-report'], cwd=ROOT, check=True)
    if not args.working_tree and git('status', '--porcelain').strip():
        raise SystemExit('Source changed during preflight; review and commit the final state before packaging.')
    deleted = []
    if args.working_tree:
        files, deleted = snapshot_working_tree()
    else:
        entries = committed_tree(commit)
        check_paths([name for name, _, _ in entries])
        blobs = committed_blobs(entries)
        files = [(name, mode, blobs[object_id]) for name, mode, object_id in entries]
    scan_snapshot(files)
    if args.working_tree:
        verify_working_snapshot(files, deleted)
    if git('rev-parse', 'HEAD').decode().strip() != commit:
        raise SystemExit('Base commit changed during packaging preflight; retry after Git operations stop.')
    names = [name for name, _, _ in files]
    checksums: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for name, _, payload in files:
        checksums[name] = hashlib.sha256(payload).hexdigest()
        sizes[name] = len(payload)
    manifest = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_commit': None if args.working_tree else commit,
        'base_commit': commit, 'includes_uncommitted_changes': args.working_tree,
        'packaging_mode': 'working_tree_snapshot' if args.working_tree else 'committed_blobs',
        'source_bytes': 'Verified tracked + untracked nonignored working-tree snapshot; no Git commit was created.' if args.working_tree else 'Exact committed Git blobs; no worktree files or checkout filters.',
        'deleted_tracked_paths': deleted, 'files': checksums, 'sizes_bytes': sizes,
        'note': 'Source release. Test evidence and explicit unverified scope are in FINAL_REPORT.md. Credentials and installed dependencies are excluded. This archive does not certify cloud deployment or native device builds.',
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, mode, payload in files:
            info = zipfile.ZipInfo('AsBoljam/' + name)
            info.create_system = 3
            info.external_attr = int(mode, 8) << 16
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        archive.writestr('AsBoljam/' + MANIFEST_NAME, json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(target) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise SystemExit('ZIP CRC validation failed: ' + corrupt)
        expected_names = {'AsBoljam/' + name for name in names} | {'AsBoljam/' + MANIFEST_NAME}
        if len(archive.namelist()) != len(expected_names) or set(archive.namelist()) != expected_names:
            raise SystemExit('Unexpected or duplicate ZIP entries.')
        for name, digest in checksums.items():
            if hashlib.sha256(archive.read('AsBoljam/' + name)).hexdigest() != digest:
                raise SystemExit('Archive checksum mismatch: ' + name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with checksum_path.open('x', encoding='ascii') as handle:
        handle.write(digest + '  ' + target.name + '\n')
    print(json.dumps({'archive': str(target.relative_to(ROOT)), 'source_commit': manifest['source_commit'], 'base_commit': commit, 'packaging_mode': manifest['packaging_mode'], 'includes_uncommitted_changes': args.working_tree, 'files': len(names), 'bytes': target.stat().st_size, 'sha256': digest, 'crc_and_all_file_hashes': 'PASS'}, indent=2))

if __name__ == '__main__':
    main()
