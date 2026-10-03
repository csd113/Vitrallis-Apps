"""Opt-in GUI workflows from immutable payloads with disposable external AppData."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog_lib import ROOT, file_rows, local_files, package_files
from simulate_install import stage

HARNESS='''
import json, pathlib, sys, tkinter as tk
sys.dont_write_bytecode=True
package=pathlib.Path(sys.argv[1]);slug=sys.argv[2]
sys.path.insert(0,str(package))
root=tk.Tk()
if slug=='vitrallis-debug':
    from monitor_ui import Monitor
    from demo import DemoCollector
    app=Monitor(root,tk,DemoCollector(),demo=True)
    app.snapshot=DemoCollector().collect()
    app.save_report()
    assert list(app.paths.documents.glob('Diagnostics-*.txt'))
else:
    import main
    app=main.App(root)
    if slug=='calculator':
        for key in '2+3=':app.press(key)
        assert app.model.result=='5'
    elif slug=='music':
        app.player.volume=43
        app.toggle_shuffle()
    else:
        app.model.begin(0,0);app.model.stroke(463,193);app.model.end()
        app.model.save(app.paths.documents/'Drawing.png')
        app.model.open(app.paths.documents/'Drawing.png')
        assert app.model.image.getpixel((0,0)) != (255,255,255)
root.update()
app.close()
if slug!='calculator':
    state=pathlib.Path(__import__('os').environ['VITRALLIS_APP_DATA_DIR'])
    if slug=='music':assert json.loads((state/'config/settings.json').read_text())['volume']==43
    if slug=='sketch':assert (state/'Documents/Drawing.png').is_file()
'''


@unittest.skipUnless(os.environ.get('VITRALLIS_REQUIRE_GUI')=='1','Opt-in staged GUI workflows')
class StagedWorkflows(unittest.TestCase):
    def check_app(self,slug):
        files=local_files(ROOT/'apps'/slug)
        with tempfile.TemporaryDirectory() as t:
            base=Path(t).resolve();home=base/'home';home.mkdir()
            package=base/'package'
            metadata=stage(files,package)
            data=home/'Documents/Vitrallis/AppData'/metadata['id']
            env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
            env.update(HOME=str(home),VITRALLIS_APP_ID=metadata['id'],VITRALLIS_APP_DIR=str(package),
                       VITRALLIS_APP_DATA_DIR=str(data),VITRALLIS_DOCUMENTS_DIR=str(data/'Documents'),
                       XDG_CACHE_HOME=str(home/'cache'),PYTHONDONTWRITEBYTECODE='1')
            try:
                subprocess.run([sys.executable,'-B','-s','-c',HARNESS,str(package),slug],env=env,cwd=home,check=True,timeout=20)
                self.assertEqual(file_rows(local_files(package)),file_rows(package_files(files)))
            finally:
                for p in package.rglob('*'):
                    if p.is_dir():p.chmod(0o755)
                package.chmod(0o755)
            # Package replacement and removal have no authority over external data.
            expected={str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*') if p.is_file()}
            shutil.rmtree(package)
            stage(files,package)
            try:
                self.assertEqual(expected,{str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*') if p.is_file()})
            finally:
                for p in package.rglob('*'):
                    if p.is_dir():p.chmod(0o755)
                package.chmod(0o755)
            shutil.rmtree(package)
            self.assertEqual(expected,{str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*') if p.is_file()})

    def test_calculator(self):self.check_app('calculator')
    def test_music(self):self.check_app('music')
    def test_sketch(self):self.check_app('sketch')
    def test_system_monitor(self):self.check_app('vitrallis-debug')
