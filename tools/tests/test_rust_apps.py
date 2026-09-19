import importlib.util
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import build_rust_app
from catalog_lib import Invalid, file_rows, local_files, manifest, package_files


class RustBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'source'
        shutil.copytree(TOOLS.parent / 'examples/hello-rust', self.source)

    def compiler(self, args, check):
        target = args[args.index('--target') + 1]
        output = Path(args[args.index('--target-dir') + 1]) / target / 'release/hello-vitrallis-rust'
        output.parent.mkdir(parents=True)
        payload = bytearray(128)
        payload[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<H', payload, 18, 40)
        struct.pack_into('<I', payload, 36, 0x400)
        output.write_bytes(payload)

    def test_staging_is_catalog_compatible_and_retains_executable_mode(self):
        output = self.root / 'package'
        with patch('build_rust_app.subprocess.run', side_effect=self.compiler):
            build_rust_app.build(self.source, output, ['armv7-unknown-linux-gnueabihf'])
        files = local_files(output)
        metadata = manifest(files, output)
        self.assertEqual(metadata['runtime'], 'python')
        name = 'bin/armv7-unknown-linux-gnueabihf/app'
        self.assertTrue((output / name).stat().st_mode & 0o111)
        rows = file_rows(package_files(files))
        self.assertIn(name, [row['path'] for row in rows])
        self.assertFalse(any(row['path'].startswith('tests/') for row in rows))
        self.assertIn('assets/greeting.txt', files)
        with self.assertRaises(Invalid):
            build_rust_app.build(self.source, output, ['armv7-unknown-linux-gnueabihf'])

    def test_bad_target_and_failed_build_leave_no_package(self):
        output = self.root / 'package'
        for targets in ([], ['../../escape'], ['armv7-unknown-linux-gnueabihf'] * 2):
            with self.assertRaises(Invalid):
                build_rust_app.build(self.source, output, targets)
        with patch('build_rust_app.subprocess.run', side_effect=OSError('compiler unavailable')):
            with self.assertRaises(OSError):
                build_rust_app.build(self.source, output, ['armv7-unknown-linux-gnueabihf'])
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.vitrallis-rust-stage-*')))

    def test_foreign_payload_is_rejected_before_staging(self):
        output = self.root / 'package'
        with patch('build_rust_app.subprocess.run', side_effect=self.compiler):
            with self.assertRaisesRegex(Invalid, 'matching'):
                build_rust_app.build(self.source, output, ['aarch64-unknown-linux-gnu'])
        self.assertFalse(output.exists())

    def test_publication_preserves_concurrently_created_empty_directory(self):
        staged = self.root / 'staged'
        staged.mkdir()
        (staged / 'payload').write_bytes(b'complete')
        destination = self.root / 'concurrent'
        destination.mkdir()
        inode = destination.stat().st_ino
        with self.assertRaises(FileExistsError):
            build_rust_app.publish_directory(staged, destination)
        self.assertEqual(destination.stat().st_ino, inode)
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual((staged / 'payload').read_bytes(), b'complete')
