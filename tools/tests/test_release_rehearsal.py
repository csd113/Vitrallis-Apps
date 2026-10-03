"""Rehearse the four-app release in a disposable Git fixture, without publication."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog_lib import ROOT


class ReleaseRehearsal(unittest.TestCase):
    def test_source_first_generated_catalog_and_release_policy(self):
        with tempfile.TemporaryDirectory() as t:
            repo=Path(t).resolve()/'source'
            def run(*args):
                result=subprocess.run(args,cwd=repo,capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stderr or result.stdout)
                return result.stdout.strip()
            subprocess.run(['git','clone','--shared','--quiet',str(ROOT),str(repo)],check=True,timeout=30)
            run('git','config','user.name','Release fixture')
            run('git','config','user.email','fixture@example.invalid')
            # Rehearse from before these new apps existed, including when the
            # test itself runs from the completed source/catalog release.
            creation=run('git','log','--diff-filter=A','--format=%H','--','apps/music/app.toml').splitlines()
            if creation:
                run('git','checkout','--quiet','--detach',creation[-1]+'^')
            base=run('git','rev-parse','HEAD')
            for slug in ('calculator','music','sketch','vitrallis-debug'):
                target=repo/'apps'/slug
                if target.exists():shutil.rmtree(target)
                shutil.copytree(ROOT/'apps'/slug,target)
            # Only this goal's package edits enter the disposable fixture.
            run('git','add','apps/calculator','apps/music','apps/sketch','apps/vitrallis-debug')
            run('git','commit','--quiet','-m','Fixture source for four-app release')
            source=run('git','rev-parse','HEAD')
            for slug in ('calculator','music','sketch','vitrallis-debug'):
                run(sys.executable,str(ROOT/'tools/update_catalog.py'),'--repo',str(repo),'--catalog',str(repo/'apps.json'),
                    '--repository','csd113/Vitrallis-Apps','--commit',source,'--path','apps/'+slug,
                    '--description',{'calculator':'Decimal arithmetic with keyboard controls.',
                                     'music':'Browse local music, stream tracks and view album artwork.',
                                     'sketch':'Draw with touch or keys and save PNG sketches.',
                                     'vitrallis-debug':'Monitor system resources, processes and optional diagnostics.'}[slug],
                    '--compatibility-notes','Requires Python 3.11+ and system Tk. Physical PocketCHIP/App Center verification deferred.',
                    '--write')
            notes=repo/'CHANGELOG.md'
            notes.write_text(notes.read_text().replace('# Catalog changelog\n','# Catalog changelog\n\n## 2026-10-02\n\n'
                '- Updated `io.vitrallis.calculator` `0.1.1`: Disable direct-launch package bytecode writes.\n'
                '- Added `io.vitrallis.music` `0.1.0`: Add local streaming playback and keyboard music browsing.\n'
                '- Added `io.vitrallis.sketch` `0.1.0`: Add touch and keyboard drawing with atomic PNG saves.\n'
                '- Updated `io.vitrallis.debug` `0.4.0`: Add System Monitor overview, processes and diagnostics reports.\n',1))
            run('git','add','apps.json','CHANGELOG.md')
            run('git','commit','--quiet','-m','Fixture generated catalog and release history')
            run(sys.executable,str(ROOT/'tools/validate_catalog.py'),'--repo',str(repo),'--catalog',str(repo/'apps.json'))
            run(sys.executable,str(ROOT/'tools/validate_changelogs.py'),'--repo',str(repo),'--base',base)
