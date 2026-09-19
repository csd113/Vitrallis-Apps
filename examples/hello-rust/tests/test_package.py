import importlib.util
from pathlib import Path
import struct
import os
import signal
import subprocess
import sys
import time
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rust_bootstrap', SOURCE / 'main.py')
BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOT)


class PackageTests(unittest.TestCase):
    def test_target_selection_and_invalid_payload_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'bin/armv7-unknown-linux-gnueabihf/app'
            path.parent.mkdir(parents=True)
            header = bytearray(52)
            header[:7] = b'\x7fELF\x01\x01\x01'
            struct.pack_into('<H', header, 18, 40)
            struct.pack_into('<I', header, 36, 0x400)
            path.write_bytes(header)
            path.chmod(0o755)
            self.assertEqual(BOOT.executable(root, 'Linux', 'armv7l'), path)
            with self.assertRaises(ValueError):
                BOOT.executable(root, 'Darwin', 'arm64')
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                BOOT.executable(root, 'Linux', 'armv7l')
            path.chmod(0o755)
            path.write_bytes(b'not ELF')
            with self.assertRaises(ValueError):
                BOOT.executable(root, 'Linux', 'armv7l')

    def test_symlink_payload_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'bin/x86_64-unknown-linux-gnu/app'
            path.parent.mkdir(parents=True)
            path.symlink_to('/bin/sh')
            with self.assertRaises(ValueError):
                BOOT.executable(root, 'Linux', 'x86_64')

    def test_supervisor_forwards_shutdown_and_reaps_native_process(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            child_code = 'import os,pathlib,time;pathlib.Path(' + repr(str(ready)) + ').write_text(str(os.getpid()));time.sleep(30)'
            script = ('import sys;sys.path.insert(0,' + repr(str(SOURCE)) + ');'
                      'from main import supervise;sys.exit(supervise(sys.executable,' + repr(['-c', child_code]) + '))')
            process = subprocess.Popen([sys.executable, '-B', '-c', script])
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'Native child did not start')
                child = int(ready.read_text())
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 128 + signal.SIGTERM)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
