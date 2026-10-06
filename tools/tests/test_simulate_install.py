"""Tests for the package boundary; never invoke Shell or access a device."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog_lib import Invalid, ROOT, file_rows, load_json, local_files, package_files
from simulate_install import advertised, main, provision, stage


class InstallTests(unittest.TestCase):
    def test_original_calculator_failure_is_publisher_gate(self):
        catalog=load_json(ROOT/'apps.json')
        entry,files=advertised(catalog,'io.vitrallis.calculator')
        entry['installable'] = False
        self.assertIn('calculation.py',files)
        with tempfile.TemporaryDirectory() as t:
            fixture=Path(t).resolve()/'catalog.json';fixture.write_text(json.dumps(catalog))
            self.assertEqual(main(['--app','io.vitrallis.calculator','--catalog',str(fixture)]),1)

    def test_wrong_hash_incomplete_inventory_and_manifest_rejected(self):
        original=load_json(ROOT/'apps.json')
        for damage in ('hash','missing','version'):
            catalog=copy.deepcopy(original)
            entry=next(a for a in catalog['apps'] if a['id']=='io.vitrallis.calculator')
            if damage=='hash':entry['files'][0]['sha256']='0'*64
            elif damage=='missing':entry['files'].pop()
            else:entry['version']='9.0.0'
            with self.subTest(damage=damage),self.assertRaises(Invalid):advertised(catalog,'io.vitrallis.calculator')

    def test_calculator_stage_readonly_import_and_launch_outside_checkout(self):
        files=local_files(ROOT/'apps/calculator')
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();package=root/'application'
            stage(files,package)
            try:
                self.assertEqual(file_rows(local_files(package)),file_rows(package_files(files)))
                self.assertFalse((package/'tests').exists())
                self.assertEqual((package/'main.py').stat().st_mode&0o222,0)
                code="import sys;sys.path.insert(0,sys.argv[1]);import main;assert main.VERSION=='0.1.1';assert main.Calculator().result=='0'"
                subprocess.run([sys.executable,'-c',code,str(package)],cwd=root,env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')},check=True,timeout=10)
                self.assertFalse((package/'__pycache__').exists())
                if os.geteuid()!=0:
                    with self.assertRaises(PermissionError):(package/'unauthorized').write_text('mutation')
            finally:
                for p in package.rglob('*'):
                    if p.is_dir():p.chmod(0o755)
                package.chmod(0o755)

    def test_symlink_and_missing_required_file_fail_before_staging(self):
        files=local_files(ROOT/'apps/calculator')
        for name in ('icon.png','calculation.py','app.toml'):
            invalid=dict(files);invalid.pop(name)
            with tempfile.TemporaryDirectory() as t:
                destination=Path(t)/'app'
                if name=='calculation.py':
                    stage(invalid,destination)
                    try:
                        p=subprocess.run([sys.executable,'-B','-s',str(destination/'main.py')],capture_output=True,timeout=10)
                        self.assertNotEqual(p.returncode,0)
                        self.assertIn(b'calculation',p.stderr)
                    finally:
                        for d in destination.rglob('*'):
                            if d.is_dir():d.chmod(0o755)
                        destination.chmod(0o755)
                else:
                    with self.assertRaises(Invalid):stage(invalid,destination)
                    self.assertFalse(destination.exists())

    def test_dependency_options_urls_and_paths_never_reach_pip(self):
        with tempfile.TemporaryDirectory() as t:
            package=Path(t)/'app';package.mkdir()
            for requirement in ('--target /tmp/foo','https://example.test/pkg','../pkg','Name[extra]'):
                (package/'requirements.txt').write_text(requirement)
                with patch('simulate_install.venv.EnvBuilder') as builder,self.assertRaises(Invalid):provision(package,Path(t)/'runtime',True)
                builder.assert_not_called()
