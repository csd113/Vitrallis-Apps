#!/usr/bin/env python3
"""Package-side staging audit, not an App Center installer or device certificate."""
import argparse
import hashlib
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import venv

from catalog_lib import (Invalid, ROOT, catalog_metadata, check_app_source,
                         committed_files, file_rows, load_json, local_files,
                         manifest, package_files, require)


def advertised(catalog, app_id, repo=ROOT):
    catalog_metadata(catalog)
    selected = next((app for app in catalog['apps'] if app['id'] == app_id), None)
    require(selected is not None, app_id, 'app not in catalog')
    check_app_source(selected, repo)
    return selected, committed_files(repo, selected['source']['commit'], selected['source']['path'])


def stage(files, destination):
    """Only validated inventory bytes enter a fresh, caller-owned directory."""
    metadata = manifest(files, destination)
    require(metadata['runtime'] == 'python', destination, 'Python audit only')
    payload = package_files(files)
    destination.mkdir()
    for name, data in payload.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)
    for directory in sorted((p for p in destination.rglob('*') if p.is_dir()), reverse=True):
        directory.chmod(0o555)
    destination.chmod(0o555)
    return metadata


def provision(package, runtime, allow_download=False):
    """Exercise system-site venv selection and distribution checks independently."""
    requirements = []
    for raw in (package / 'requirements.txt').read_text().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        # Deliberately conservative subset for this package audit. No pip options,
        # paths, URLs, extras, continuation lines or executable directives.
        pattern = r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\s*(?:===|==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!-]+(?:\s*,\s*(?:===|==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!-]+)*)?'
        require(re.fullmatch(pattern, line) is not None, line, 'Unsupported requirement syntax in package audit')
        requirements.append(line)
    digest = hashlib.sha256((package / 'requirements.txt').read_bytes()).hexdigest()
    environment = runtime / digest
    venv.EnvBuilder(system_site_packages=True, with_pip=True).create(environment)
    python = environment / 'bin/python3'
    probe = """
import importlib.metadata as m, sys
from packaging.requirements import Requirement
import tkinter
for raw in sys.argv[1:]:
    r = Requirement(raw)
    if r.marker and not r.marker.evaluate(): continue
    try: version = m.version(r.name)
    except m.PackageNotFoundError: raise SystemExit('Missing distribution: '+r.name)
    if not r.specifier.contains(version): raise SystemExit('Incompatible distribution: '+r.name)
"""
    result = subprocess.run([str(python), '-I', '-c', probe, *requirements], capture_output=True, text=True, timeout=30)
    if result.returncode and allow_download:
        env = {key: value for key, value in os.environ.items() if not key.startswith(('PIP_', 'PYTHON'))}
        env['PIP_CONFIG_FILE'] = os.devnull
        subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--no-cache-dir', '-r', str(package / 'requirements.txt'), 'packaging'],
                       env=env, check=True, timeout=180)
        result = subprocess.run([str(python), '-I', '-c', probe, *requirements], capture_output=True, text=True, timeout=30)
    require(result.returncode == 0, package, result.stderr.strip() or result.stdout.strip() or 'Runtime dependency probe failed')
    return python


def audit(files, *, gui=False, allow_download=False):
    with tempfile.TemporaryDirectory(prefix='vitrallis-install-') as temporary:
        base = Path(temporary).resolve()
        package = base / 'application'
        metadata = stage(files, package)
        try:
            # Runtime is a separate installer-owned tree. Package payload stays read-only.
            python = provision(package, base / 'runtime', allow_download)
            home = base / 'home'
            home.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.startswith('PYTHON')}
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                       XDG_DATA_HOME=str(home / 'data'), XDG_CACHE_HOME=str(home / 'cache'),
                       VITRALLIS_APP_ID=metadata['id'], VITRALLIS_APP_DIR=str(package),
                       VITRALLIS_APP_DATA_DIR=str(home / 'Documents/Vitrallis/AppData' / metadata['id']),
                       VITRALLIS_DOCUMENTS_DIR=str(home / 'Documents/Vitrallis/AppData' / metadata['id'] / 'Documents'),
                       PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
            code = """
import pathlib, runpy, sys
sys.dont_write_bytecode = True
p = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(p.parent))
for f in p.parent.rglob('*.py'): compile(f.read_bytes(), str(f), 'exec')
runpy.run_path(str(p), run_name='staged_import')
"""
            subprocess.run([str(python), '-I', '-c', code, str(package / metadata['entry'])],
                           cwd=home, env=env, check=True, timeout=30)
            if gui:
                data = Path(env['VITRALLIS_APP_DATA_DIR'])
                data.mkdir(mode=0o700, parents=True, exist_ok=True)
                for iteration in range(2):
                    process = subprocess.Popen([str(python), '-B', '-s', str(package / metadata['entry'])],
                                               cwd=data if iteration == 0 else home, env=env,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        time.sleep(1.5)
                        require(process.poll() is None, metadata['id'], 'Entry exited before GUI smoke completed')
                        process.send_signal(signal.SIGTERM)
                        _, error = process.communicate(timeout=8)
                        require(process.returncode == 0, metadata['id'], error.decode(errors='replace'))
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.communicate()
            require(file_rows(local_files(package)) == file_rows(package_files(files)), package, 'Package mutated at runtime')
            return metadata
        finally:
            for path in package.rglob('*'):
                if path.is_dir():
                    path.chmod(0o755)
            package.chmod(0o755)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--app', help='catalog app ID')
    selection.add_argument('--package', type=Path, help='unpublished working package')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'apps.json')
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--audit-unavailable', action='store_true', help='audit disabled payload; does not establish installation eligibility')
    parser.add_argument('--gui', action='store_true', help='launch twice and exercise TERM; needs a display')
    parser.add_argument('--provision', action='store_true', help='allow pip downloads into disposable runtime')
    args = parser.parse_args(argv)
    try:
        if args.package:
            files = local_files(args.package)
        else:
            entry, files = advertised(load_json(args.catalog), args.app, args.repo)
            require(entry['installable'] or args.audit_unavailable, args.app, 'Publisher disabled installation (installable: false)')
            if not entry['installable']:
                print('UNAVAILABLE: publisher disabled; auditing payload only')
        result = audit(files, gui=args.gui, allow_download=args.provision)
        print(f"OK: {result['id']} {result['version']} read-only staged import" + (' and repeated GUI/TERM' if args.gui else ''))
        return 0
    except (Invalid, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
