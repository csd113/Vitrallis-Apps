import os
import subprocess
import sys
import tempfile
import tomllib
import unittest

from support import PACKAGE


class PackageTests(unittest.TestCase):
    def test_manifest_contract_identity_and_package_validator(self):
        manifest = tomllib.loads((PACKAGE / "app.toml").read_text())
        self.assertEqual(manifest["id"], "io.vitrallis.mediacarousel")
        self.assertEqual(manifest["version"], "0.2.0")
        self.assertEqual(manifest["name"], "Vitrallis Media Carousel")
        self.assertEqual(manifest["permissions"], {"network": True, "storage": True, "audio": False})
        repo = PACKAGE.parents[1]
        result = subprocess.run([sys.executable, "-B", str(repo / "tools/validate_catalog.py"),
                                 "--package", str(PACKAGE)], cwd=repo, capture_output=True,
                                text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_module_imports_have_no_windows_threads_network_or_writes(self):
        code = '''
import sys, tkinter, socket, threading, subprocess, os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
with patch.object(tkinter, 'Tk', side_effect=AssertionError('Tk on import')), \\
     patch.object(socket.socket, 'bind', side_effect=AssertionError('bind on import')), \\
     patch.object(socket.socket, 'connect', side_effect=AssertionError('connect on import')), \\
     patch.object(threading.Thread, 'start', side_effect=AssertionError('thread on import')), \\
     patch.object(subprocess, 'Popen', side_effect=AssertionError('process on import')), \\
     patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir on import')), \\
     patch.object(os, 'open', side_effect=AssertionError('open on import')):
    import main, storage, settings, library, media, player, web_server, ui, gpu
    import connection, dependencies, multimedia, previews
assert main.VERSION == '0.2.0'
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", code, str(PACKAGE)], cwd=directory,
                                    capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_uses_python_39_syntax(self):
        import ast
        for path in PACKAGE.glob("*.py"):
            ast.parse(path.read_text(), feature_version=(3, 9))

    def test_no_cache_files_inside_package(self):
        self.assertEqual(list(PACKAGE.rglob("*.pyc")), [])
        self.assertEqual(list(PACKAGE.rglob("__pycache__")), [])
