"""Rehearse the four-app release in a disposable Git fixture, without publication."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog_lib import ROOT, file_rows, local_files, package_files


class ReleaseRehearsal(unittest.TestCase):
    def test_source_first_generated_catalog_and_release_policy(self):
        with tempfile.TemporaryDirectory() as t:
            repo=Path(t).resolve()/'source'
            def run(*args):
                result=subprocess.run(args,cwd=repo,capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stderr or result.stdout)
                return result.stdout.strip()
            subprocess.run(['git','clone','--no-local','--quiet',str(ROOT),str(repo)],check=True,timeout=30)
            run('git','config','user.name','Release fixture')
            run('git','config','user.email','fixture@example.invalid')
            # Rehearse from before these new apps existed, including when the
            # test itself runs from the completed source/catalog release.
            creation=run('git','log','--diff-filter=A','--format=%H','--','apps/music/app.toml').splitlines()
            if creation:
                run('git','checkout','--quiet','--detach',creation[-1]+'^')
            baseline=run('git','rev-parse','HEAD')
            # External pins are fixture-only snapshots of identical local mirrors.
            # Do not rely on unreachable external objects cached in the Apps repo.
            catalog=json.loads((repo/'apps.json').read_text())
            mappings=[]
            for entry in catalog['apps']:
                repository=entry['source']['repository']
                if repository!='csd113/Vitrallis-Apps':
                    self.assertEqual(entry['files'],file_rows(package_files(local_files(repo/entry['source']['path']))))
                    entry['source']['commit']=baseline
                    option=['--source-repo',repository+'='+str(repo)]
                    if option[1] not in mappings:mappings.extend(option)
            if mappings:
                (repo/'apps.json').write_text(json.dumps(catalog,indent=2)+'\n')
                run('git','add','apps.json')
                run('git','commit','--quiet','-m','Fixture external sources from verified local mirrors')
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
                    *mappings,'--repository','csd113/Vitrallis-Apps','--commit',source,'--path','apps/'+slug,
                    '--description',{'calculator':'Decimal arithmetic with keyboard controls.',
                                     'music':'Browse local music, stream tracks and view album artwork.',
                                     'sketch':'Draw with touch or keys and save PNG sketches.',
                                     'vitrallis-debug':'Monitor system resources, processes and optional diagnostics.'}[slug],
                    '--compatibility-notes','Requires Python 3.11+ and system Tk. Physical PocketCHIP/App Center verification deferred.',
                    '--write')
            notes=repo/'CHANGELOG.md'
            # The fixture copies current working packages, including later fixes.
            # Its catalog history must describe those generated versions too.
            generated=json.loads((repo/'apps.json').read_text())
            releases=[]
            dates=[]
            for entry in generated['apps']:
                if entry['source']['commit']!=source:continue
                changelog=(repo/entry['source']['path']/'CHANGELOG.md').read_text()
                heading=re.search(r'^## [^\n]+ — (\d{4}-\d{2}-\d{2})$',changelog,re.MULTILINE)
                self.assertIsNotNone(heading)
                dates.append(heading.group(1))
                summary=re.search(r'^- (.+)$',changelog,re.MULTILINE)
                self.assertIsNotNone(summary)
                action='Added' if entry['id'] in ('io.vitrallis.music','io.vitrallis.sketch') else 'Updated'
                releases.append(f"- {action} `{entry['id']}` `{entry['version']}`: {summary.group(1)}\n")
            self.assertEqual(len(releases),4)
            notes.write_text(notes.read_text().replace('# Catalog changelog\n',
                '# Catalog changelog\n\n## '+max(dates)+'\n\n'+''.join(releases),1))
            run('git','add','apps.json','CHANGELOG.md')
            run('git','commit','--quiet','-m','Fixture generated catalog and release history')
            run(sys.executable,str(ROOT/'tools/validate_catalog.py'),'--repo',str(repo),'--catalog',str(repo/'apps.json'),*mappings)
            run(sys.executable,str(ROOT/'tools/validate_changelogs.py'),'--repo',str(repo),'--base',base,*mappings)
