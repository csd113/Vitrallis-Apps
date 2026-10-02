#!/usr/bin/env python3
"""Select affected runtime suites without importing or launching applications."""
import argparse
import ast
import json
import os
import tempfile
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {'.md', '.rst'}
METADATA = {'app.toml', 'icon.png', 'LICENSE', 'requirements.txt'}


def packages(root):
    found = []
    for folder in ('apps', 'examples'):
        for path in (root / folder).glob('*/app.toml'):
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise ValueError('Unsafe package manifest path')
            found.append(path.parent)
    return sorted(found)


def runtime_change(path, package):
    relative = path.relative_to(package)
    if relative.parts[0] == 'tests':
        return True
    if relative.as_posix() == 'requirements.txt':
        return True  # A dependency change can alter startup and rendering.
    return relative.name not in METADATA and relative.suffix not in DOCUMENTS


def dependencies(root, package, changed=()):
    """Resolve local Python imports and Cargo path dependencies conservatively.

    Dynamic dependencies must be declared in test-dependencies.json. Unknown
    Python imports are external dependencies, not a reason to boot every app.
    """
    found = {package}
    pending = list(package.rglob('*.py'))
    visited = set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        if (source.is_symlink() or not source.is_file() or source.stat().st_size > 4_000_000
                or not source.resolve().is_relative_to(root)):
            raise ValueError('Unsafe Python dependency path')
        tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
                bases = (source.parent, package, root)
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module + '.' if node.module else ''
                names = ([node.module] if node.module else []) + [prefix + item.name for item in node.names if item.name != '*']
                if node.level:
                    base = source.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    bases = (base,)
                else:
                    bases = (source.parent, package, root)
            else:
                continue
            for name in names:
                parts = name.split('.')
                for base in bases:
                    candidate = base.joinpath(*parts)
                    for target in (candidate.with_suffix('.py'), candidate / '__init__.py'):
                        if (target.is_file() or target in changed) and target.is_relative_to(root):
                            found.add(target)
                            if target.is_file():
                                pending.append(target)
    manifests = list(package.rglob('Cargo.toml'))
    checked = set()
    while manifests:
        manifest = manifests.pop()
        if manifest in checked:
            continue
        checked.add(manifest)
        if manifest.is_symlink() or not manifest.is_file() or not manifest.resolve().is_relative_to(root):
            raise ValueError('Unsafe Cargo dependency manifest')
        data = tomllib.loads(manifest.read_text())
        tables = [data, *data.get('target', {}).values()]
        for table in tables:
            for section in ('dependencies', 'dev-dependencies', 'build-dependencies'):
                for name, value in table.get(section, {}).items():
                    origin = manifest.parent
                    if isinstance(value, dict) and value.get('workspace'):
                        for ancestor in manifest.parents:
                            if not ancestor.is_relative_to(root):
                                break
                            workspace = ancestor / 'Cargo.toml'
                            if workspace.is_file():
                                inherited = tomllib.loads(workspace.read_text()).get('workspace', {}).get('dependencies', {})
                                if name in inherited:
                                    value, origin = inherited[name], ancestor
                                    break
                    if isinstance(value, dict) and 'path' in value:
                        target = (origin / value['path']).resolve()
                        if not target.is_relative_to(root):
                            raise ValueError('Cargo dependency escapes repository')
                        found.add(target)
                        if (target / 'Cargo.toml').is_file():
                            manifests.append(target / 'Cargo.toml')
    declaration = package / 'test-dependencies.json'
    if declaration.exists():
        if declaration.is_symlink() or not declaration.is_file() or declaration.stat().st_size > 16384:
            raise ValueError('Unsafe dependency declaration')
        declared = json.loads(declaration.read_text())
        if not isinstance(declared, list) or any(not isinstance(value, str) or not value or Path(value).is_absolute() for value in declared):
            raise ValueError('Dependencies must be a list of repository-relative paths')
        for value in declared:
            target = (root / value).resolve()
            if not target.is_relative_to(root) or not target.exists():
                raise ValueError('Invalid declared test dependency')
            found.add(target)
    return found


def select(root, changed, explicit=()):
    root = root.resolve()
    available = packages(root)
    selected = set()
    for value in explicit:
        package = (root / value).resolve()
        if package not in available:
            raise ValueError(f'Unknown package: {value}')
        selected.add(package)
    paths = [(root / value).resolve() for value in changed]
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError('Changed path escapes repository')
    for package in available:
        for path in paths:
            if path.is_relative_to(package) and runtime_change(path, package):
                selected.add(package)
        if package not in selected:
            for dependency in dependencies(root, package, paths) - {package}:
                if any(path.is_relative_to(dependency)
                       for path in paths):
                    selected.add(package)
                    break
    return sorted(package.relative_to(root).as_posix() for package in selected)


def changed_files(root, base=None):
    if base:
        revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse',
                                            '--verify', '--end-of-options', base], text=True).strip()
        kind = subprocess.check_output(['git', '-C', str(root), 'cat-file', '-t', revision], text=True).strip()
        if kind == 'commit':
            revision = subprocess.check_output(['git', '-C', str(root), 'merge-base', revision, 'HEAD'], text=True).strip()
        elif kind != 'tree':
            raise ValueError('Base must identify a commit or tree')
        commands = [['diff', '--name-only', '--no-renames', '-z',
                     '--diff-filter=ACDMRTUXB', revision, 'HEAD', '--']]
    else:
        commands = [['diff', '--name-only', '--no-renames', '-z', 'HEAD', '--'],
                    ['ls-files', '--others', '--exclude-standard', '-z']]
    paths = set()
    for command in commands:
        output = subprocess.check_output(['git', '-C', str(root), *command])
        paths.update(value.decode('utf-8') for value in output.split(b'\0') if value)
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', help='Compare committed HEAD with this Git revision')
    parser.add_argument('--app', action='append', default=[], help='Explicit apps/slug or examples/slug')
    parser.add_argument('--run', action='store_true', help='Run selected suites in separate processes')
    args = parser.parse_args()
    try:
        selected = select(ROOT, changed_files(ROOT, args.base), args.app)
        print(json.dumps({'runtime_packages': selected}), flush=True)
        if args.run:
            for package in selected:
                subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover',
                                '-s', str(ROOT / package / 'tests'), '-v'], check=True)
                manifest = ROOT / package / 'Cargo.toml'
                if manifest.exists():
                    with tempfile.TemporaryDirectory(prefix='vitrallis-cargo-') as target:
                        environment = dict(os.environ, CARGO_TARGET_DIR=target)
                        for options in (
                            ['fmt', '--all', '--check'],
                            ['clippy', '--workspace', '--all-targets', '--all-features', '--',
                             '-D', 'warnings', '-D', 'clippy::all', '-D', 'clippy::pedantic',
                             '-D', 'clippy::nursery', '-D', 'clippy::cargo'],
                            ['test', '--workspace', '--all-features']):
                            subprocess.run(['cargo', options[0], '--manifest-path', str(manifest),
                                            *options[1:]], env=environment, check=True)
                        if package == 'examples/hello-rust':
                            staged = Path(target) / 'package'
                            subprocess.run([sys.executable, str(ROOT / 'tools/build_rust_app.py'),
                                            '--source', str(manifest.parent), '--output', str(staged),
                                            '--target', 'x86_64-unknown-linux-gnu'], check=True)
                            subprocess.run([sys.executable, str(staged / 'main.py')], check=True)
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as error:
        print(f'Scope check failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
