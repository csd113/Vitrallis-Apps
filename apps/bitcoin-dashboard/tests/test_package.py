"""Native package integration, with no real network or user storage writes."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

PACKAGE = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_manifest_matches_runtime_identity_and_version(self):
        manifest = tomllib.loads((PACKAGE / 'app.toml').read_text())
        spec = importlib.util.spec_from_file_location('bitcoin_main', PACKAGE / manifest['entry'])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(manifest['id'], 'io.vitrallis.bitcoindashboard')
        self.assertEqual(manifest['name'], 'Bitcoin Dashboard')
        self.assertEqual(manifest['version'], module.VERSION)
        self.assertEqual(manifest['entry'], 'main.py')
        self.assertEqual(manifest['permissions'],
                         {'network': True, 'audio': False, 'storage': True})

    def test_import_from_another_directory_has_no_side_effects(self):
        code = '''
import importlib.util
from pathlib import Path
import sys
import tkinter
from unittest.mock import patch
from urllib.request import OpenerDirector
spec = importlib.util.spec_from_file_location('bitcoin_main', sys.argv[1])
module = importlib.util.module_from_spec(spec)
with patch.object(tkinter, 'Tk', side_effect=AssertionError('window on import')), \\
     patch.object(OpenerDirector, 'open', side_effect=AssertionError('network on import')), \\
     patch('os.open', side_effect=AssertionError('file I/O on import')), \\
     patch.object(Path, 'mkdir', side_effect=AssertionError('write on import')):
    spec.loader.exec_module(module)
assert callable(module.main)
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-c', code, str(PACKAGE / 'main.py')],
                                    cwd=directory, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
