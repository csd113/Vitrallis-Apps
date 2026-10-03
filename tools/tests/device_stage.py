"""Copy an unpublished app snapshot into the audit's own read-only directory.

This is source-only validation, not an App Center installation or catalog pin.
It does not touch installed packages or provision dependencies.
"""

import argparse
import ast
import base64
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

APPS = {"music": "io.vitrallis.music", "vitrallis-debug": "io.vitrallis.debug",
        "sketch": "io.vitrallis.sketch",
        "firefly-field": "io.vitrallis.fireflyfield",
        "vitrallis-media-carousel": "io.vitrallis.mediacarousel"}
REMOTE_CODE = r'''
import base64,hashlib,json,os,pathlib,re,sys
payload=json.load(sys.stdin)
slug=payload['slug'];version=payload['version']
identities={'music':'io.vitrallis.music','vitrallis-debug':'io.vitrallis.debug',
            'sketch':'io.vitrallis.sketch',
            'firefly-field':'io.vitrallis.fireflyfield',
            'vitrallis-media-carousel':'io.vitrallis.mediacarousel'}
assert identities.get(slug)==payload['id']
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version)
fingerprint=payload['fingerprint'];assert re.fullmatch('[0-9a-f]{64}',fingerprint)
inventory=[{k:v for k,v in row.items() if k!='data'} for row in payload['files']]
assert hashlib.sha256(json.dumps(inventory,sort_keys=True).encode()).hexdigest()==fingerprint
folder=pathlib.Path.home()/'vitrallis-apps-hardware-2026-10-03/source'/(slug+'-'+version+'-'+fingerprint[:12])
assert not folder.exists() and not folder.is_symlink(),'Snapshot already exists'
for p in folder.parents:assert not p.is_symlink(),'Symlink ancestor'
files=[];size=0;assert len(payload['files'])<=256
for row in payload['files']:
    path=pathlib.PurePosixPath(row['path'])
    assert not path.is_absolute() and path.parts and all(p not in ('.','..') for p in path.parts)
    assert str(path)==row['path'] and chr(92) not in row['path']
    data=base64.b64decode(row['data'],validate=True)
    assert len(data)<=2*1024*1024 and hashlib.sha256(data).hexdigest()==row['sha256']
    size+=len(data);files.append((path,data));assert size<=16*1024*1024
assert len({str(p) for p,d in files})==len(files)
os.umask(0o077);folder.mkdir(parents=True,mode=0o700)
for path,data in files:
    target=folder/path;target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    target.write_bytes(data);target.chmod(0o444)
for path in sorted(folder.rglob('*'),reverse=True):
    if path.is_dir():path.chmod(0o555)
folder.chmod(0o555)
print(json.dumps({'snapshot':str(folder),'files':len(files),'bytes':size,'app_id':payload['id']}))
'''

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", choices=APPS)
    parser.add_argument("--package", type=Path, help="Explicit source-only comparison package")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    app = args.package.resolve() if args.package else root / "apps" / args.app
    manifest = tomllib.loads((app / "app.toml").read_text())
    if manifest["id"] != APPS[args.app]:
        parser.error("Manifest identity mismatch")
    files = []
    for path in sorted(app.rglob("*")):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink():
            parser.error("Source snapshot contains a symlink")
        if path.is_file():
            data = path.read_bytes()
            files.append({"path": str(path.relative_to(app)),
                          "sha256": hashlib.sha256(data).hexdigest(),
                          "data": base64.b64encode(data).decode("ascii")})
    payload = {"slug": args.app, "id": manifest["id"],
               "version": manifest["version"], "files": files}
    inventory = [{k:v for k,v in row.items() if k != "data"} for row in files]
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    payload["fingerprint"] = fingerprint
    # Keep code separate from input: stdin is the validated JSON snapshot.
    import shlex
    command = "python3 -I -B -c " + shlex.quote(REMOTE_CODE)
    ast.parse(REMOTE_CODE)
    result = subprocess.run(["ssh", "-oBatchMode=yes", "-oConnectTimeout=10",
                             "chip@192.168.81.1", command],
                            input=json.dumps(payload), text=True, capture_output=True,
                            check=False, timeout=45)
    if result.returncode:
        raise SystemExit("Snapshot failed: " + result.stderr.strip())
    folder = root / "target/apps-hardware-2026-10-03"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (args.app + "-" + manifest["version"] + "-" + fingerprint[:12] + "-inventory.json")).write_text(
        json.dumps({"metadata": json.loads(result.stdout), "files": inventory}, indent=2) + "\n")
    print(result.stdout.strip())
