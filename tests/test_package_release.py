"""Focused packaging tests use fabricated files and read-only Git responses."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import package_release as package

COMMIT = 'a' * 40
OBJECT = 'b' * 40


class PackageReleaseTests(unittest.TestCase):
    def fake_git(self, names=('README.md',), dirty=False):
        def response(*args):
            if args == ('status', '--porcelain'):
                return b' M README.md\n' if dirty else b''
            if args[0] == 'rev-parse':
                return (COMMIT + '\n').encode()
            if args == ('ls-files', '--cached', '--others', '--exclude-standard', '-z'):
                return ('\0'.join(names) + '\0').encode()
            if args == ('ls-files', '--deleted', '-z'):
                return b''
            self.fail('Unexpected Git operation: ' + repr(args))
        return response

    def run_package(self, root, *, working=False, names=('README.md',), dirty=False):
        argv = ['package_release.py', '--output', 'releases/test.zip'] + (['--working-tree'] if working else [])
        with patch.object(package, 'ROOT', root), patch.object(package, 'REQUIRED', {'README.md'}), \
             patch.object(package, 'git', side_effect=self.fake_git(names, dirty)) as git_call, \
             patch.object(package.subprocess, 'run') as secret_scan, \
             patch.object(package.sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()) as output:
            package.main()
        self.assertTrue(secret_scan.call_args.kwargs['check'])
        return json.loads(output.getvalue()), git_call.call_args_list

    def test_exclusions_are_case_insensitive_and_cover_sidecars_and_key_stores(self):
        blocked = ['.CACHE/a.csv', 'Node_Modules/a.js', '.ENV.production', 'db.DUMP', 'mobile/release.JKS',
                   'signing.KEYSTORE', 'data/test.db-WAL', 'data/test.sqlite3-shm', 'data/test.sqlite-journal',
                   '../private.txt', '/absolute.txt', 'nested\\file.py', 'a:stream', 'RELEASE_MANIFEST.json']
        for name in blocked:
            with self.subTest(name=name):
                self.assertFalse(package.allowed(name))
        self.assertTrue(package.allowed('.env.example'))
        self.assertTrue(package.allowed('docs/README.md'))

    def test_default_archive_uses_commit_blobs_even_when_worktree_bytes_differ(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'README.md').write_bytes(b'worktree bytes must not enter committed release')
            committed = b'exact committed bytes\n'
            with patch.object(package, 'committed_tree', return_value=[('README.md', '100644', OBJECT)]), \
                 patch.object(package, 'committed_blobs', return_value={OBJECT: committed}):
                report, _ = self.run_package(root)
            with zipfile.ZipFile(root / 'releases/test.zip') as archive:
                self.assertEqual(archive.read('AsBoljam/README.md'), committed)
                manifest = json.loads(archive.read('AsBoljam/RELEASE_MANIFEST.json'))
            self.assertEqual(manifest['source_commit'], COMMIT)
            self.assertFalse(manifest['includes_uncommitted_changes'])
            self.assertEqual(manifest['files']['README.md'], hashlib.sha256(committed).hexdigest())
            self.assertEqual(report['crc_and_all_file_hashes'], 'PASS')

    def test_default_mode_refuses_dirty_tree_before_scan_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(SystemExit, 'must be clean'):
                self.run_package(root, dirty=True)
            self.assertFalse((root / 'releases').exists())

    def test_working_tree_mode_records_null_source_commit_and_includes_untracked_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'README.md').write_bytes(b'current uncommitted documentation\r\n')
            (root / 'new.py').write_bytes(b'print("untracked source")\n')
            report, git_calls = self.run_package(root, working=True, names=('README.md', 'new.py'), dirty=True)
            with zipfile.ZipFile(root / 'releases/test.zip') as archive:
                manifest = json.loads(archive.read('AsBoljam/RELEASE_MANIFEST.json'))
                self.assertEqual(archive.read('AsBoljam/new.py'), (root / 'new.py').read_bytes())
                self.assertEqual(archive.read('AsBoljam/README.md'), (root / 'README.md').read_bytes())
            self.assertIsNone(manifest['source_commit'])
            self.assertEqual(manifest['base_commit'], COMMIT)
            self.assertTrue(manifest['includes_uncommitted_changes'])
            self.assertEqual(report['packaging_mode'], 'working_tree_snapshot')
            self.assertTrue(all(call.args[0] in {'rev-parse', 'ls-files'} for call in git_calls))

    def test_existing_zip_and_existing_checksum_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'README.md').write_bytes(b'source')
            self.run_package(root, working=True)
            before = (root / 'releases/test.zip').read_bytes()
            with self.assertRaisesRegex(SystemExit, 'Output exists'):
                self.run_package(root, working=True)
            self.assertEqual((root / 'releases/test.zip').read_bytes(), before)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'releases').mkdir()
            checksum = root / 'releases/test.zip.sha256'; checksum.write_text('preserve me')
            with self.assertRaisesRegex(SystemExit, 'Checksum output exists'):
                self.run_package(root, working=True)
            self.assertEqual(checksum.read_text(), 'preserve me')
            self.assertFalse((root / 'releases/test.zip').exists())

    def test_snapshot_verification_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'README.md'; source.write_bytes(b'before')
            with patch.object(package, 'ROOT', root), patch.object(package, 'REQUIRED', {'README.md'}), \
                 patch.object(package, 'git', side_effect=self.fake_git()):
                files, deleted = package.snapshot_working_tree()
                source.write_bytes(b'after')
                with self.assertRaisesRegex(SystemExit, 'bytes changed'):
                    package.verify_working_snapshot(files, deleted)

    def test_snapshot_verification_rejects_changed_file_list(self):
        with patch.object(package, 'working_tree_paths', return_value=(['README.md', 'new.py'], [])):
            with self.assertRaisesRegex(SystemExit, 'file list changed'):
                package.verify_working_snapshot([('README.md', '100644', b'original')], [])

    def test_snapshot_secret_scanner_rejects_bytes_without_echoing_secret(self):
        fabricated = ('ghp_' + 'A' * 36).encode()
        with tempfile.TemporaryDirectory() as temp, patch.object(package, 'ROOT', Path(temp)):
            with self.assertRaises(SystemExit) as error:
                package.scan_snapshot([('source.py', '100644', fabricated)])
            self.assertIn('github-token', str(error.exception))
            self.assertNotIn(fabricated.decode(), str(error.exception))
            local = 'fabricated-local-password-987654321'
            (Path(temp) / '.env').write_text('DEMO_PASSWORD=' + local)
            with self.assertRaisesRegex(SystemExit, 'known-local-secret') as error:
                package.scan_snapshot([('source.py', '100644', local.encode())])
            self.assertNotIn(local, str(error.exception))

    def test_committed_tree_refuses_symlink_and_submodule_modes(self):
        for mode, kind in [('120000', 'blob'), ('160000', 'commit')]:
            raw = f'{mode} {kind} {OBJECT}\tunsafe\0'.encode()
            with self.subTest(mode=mode), patch.object(package, 'git', return_value=raw):
                with self.assertRaisesRegex(SystemExit, 'Symlinks, submodules'):
                    package.committed_tree(COMMIT)

    def test_batch_reader_handles_binary_payload_and_rejects_wrong_object(self):
        payload = b'\x00\nx\xff'
        response = f'{OBJECT} blob {len(payload)}\n'.encode() + payload + b'\n'
        with patch.object(package.subprocess, 'check_output', return_value=response):
            self.assertEqual(package.committed_blobs([('file', '100644', OBJECT)])[OBJECT], payload)
        with patch.object(package.subprocess, 'check_output', return_value=response.replace(OBJECT.encode(), COMMIT.encode(), 1)):
            with self.assertRaisesRegex(SystemExit, 'Unexpected Git blob response'):
                package.committed_blobs([('file', '100644', OBJECT)])


if __name__ == '__main__':
    unittest.main()
