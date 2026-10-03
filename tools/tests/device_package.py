"""Read-only receipt, published-byte and AppData checks after manual UI operations."""
import argparse
import json
import re
from pathlib import Path
import shlex
import subprocess

CODE = r'''
import hashlib,json,pathlib,re,sys,time
entry=json.load(sys.stdin);app_id=entry['id'];root=pathlib.Path.home()/'Documents/Vitrallis'
if not re.fullmatch(r'io\.vitrallis\.[a-z]+',app_id):raise ValueError('Unsafe app identity')
package=root/'Apps'/app_id;receipt=package/'.vitrallis-receipt.json'
checkpoint=json.loads((pathlib.Path.home()/'vitrallis-apps-hardware-2026-10-03/data-before-reinstall.json').read_text())
def safe_file(base,relative):
    p=pathlib.PurePosixPath(relative)
    if not p.parts or p.is_absolute() or any(x in ('.','..') for x in p.parts) or str(p)!=relative:raise ValueError('Unsafe inventory path')
    target=base.joinpath(*p.parts)
    for item in (target,*target.parents):
        if item.is_symlink():raise ValueError('Symlink in checked path')
    return target
def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(262144),b''):result.update(block)
    return result.hexdigest()
started=time.monotonic();complete=False
while time.monotonic()-started<60:
    try:
        if MODE=='removed':
            launcher=pathlib.Path.home()/'.local/share/vitrallis/app-center/launchers'/app_id
            safe_file(package,'.vitrallis-receipt.json')
            safe_file(launcher.parent,app_id)
            complete=not receipt.exists() and not launcher.exists()
        else:
            r=json.loads(safe_file(package,'.vitrallis-receipt.json').read_text())
            safe_file(package,'.installation-pending')
            complete=(r.get('id')==app_id and r.get('version')==entry['version'] and r.get('commit')==entry['source']['commit'] and not (package/'.installation-pending').exists())
        if complete:break
    except (OSError,ValueError):pass
    time.sleep(1)
if not complete:raise SystemExit('Operation did not reach the expected receipt/launcher state within 60 seconds')
if MODE=='installed':
    for row in entry['files']:
        p=safe_file(package,row['path'])
        if p.stat().st_size!=row['size'] or digest(p)!=row['sha256']:raise SystemExit('Published package inventory mismatch')
rows=[r for r in checkpoint if r['app_id']==app_id]
for row in rows:
    p=safe_file(root/'AppData'/app_id,row['relative'])
    if p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:raise SystemExit('Preserved AppData hash mismatch')
print(json.dumps({'id':app_id,'state':MODE,'version':entry['version'],'published_files_verified':len(entry['files']) if MODE=='installed' else 0,'preserved_data_files':len(rows),'seconds':round(time.monotonic()-started,3)}))
'''

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('installed','removed'))
    parser.add_argument('app_id')
    args=parser.parse_args()
    if not re.fullmatch(r'io\.vitrallis\.[a-z]+',args.app_id):parser.error('Unsafe app identity')
    root=Path(__file__).resolve().parents[2]
    evidence=root/'target/apps-hardware-2026-10-03'
    entries=json.loads((evidence/'catalog-test-only.json').read_text())['apps']
    entry=next((row for row in entries if row['id']==args.app_id),None)
    if entry is None:parser.error('App must belong to the validated eight-app fixture')
    code=CODE.replace('MODE',repr(args.mode))
    result=subprocess.run(['ssh','-oBatchMode=yes','-oConnectTimeout=10','chip@192.168.81.1','python3 -I -B -c '+shlex.quote(code)],input=json.dumps(entry),capture_output=True,text=True,timeout=90)
    if result.returncode:raise SystemExit(result.stderr.strip() or result.stdout.strip())
    with (evidence/'managed-lifecycle.jsonl').open('a') as log:log.write(result.stdout)
    print(result.stdout.strip())
