#!/usr/bin/env python3
"""Generate an entry from a full source commit; preview by default, --write to save."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

from catalog_lib import (Invalid, ROOT, REPOSITORY, catalog_metadata, committed_files,
                         file_rows, package_files, legacy_version, load_json, manifest, match, require,
                         source_repositories, validate_sources, write_catalog)


def update(catalog, *, repo, mappings, repository, commit, path, app_id=None,
           description=None, compatibility_notes=None, installable=None):
    catalog_metadata(catalog)
    match(repository, REPOSITORY, 'source.repository')
    source_repo = mappings.get(repository, repo)
    files = committed_files(source_repo, commit, path)
    package = manifest(files, path) if path.startswith('apps/') or 'app.toml' in files else None
    if package:
        require(app_id is None or app_id == package['id'], path, '--app-id disagrees with manifest')
        app_id = package['id']
    require(app_id is not None, path, 'legacy packages require --app-id for an existing entry')
    previous = next((app for app in catalog['apps'] if app['id'] == app_id), None)
    require(package is not None or previous is not None, path,
            'new legacy entries need a reviewed adapter and manually reviewed metadata')
    entry = copy.deepcopy(previous) if previous else {'id': app_id, 'installable': False}
    if package:
        entry.update({key: package[key] for key in ('id', 'name', 'version', 'runtime', 'entry', 'permissions')})
    else:
        # Preserve reviewed adapter metadata; read only the literal version.
        require(previous['source']['path'] == path, path, 'legacy source path cannot change')
        require(entry['entry'] in files, path, 'legacy entry missing from committed files')
        entry['version'] = legacy_version(files[entry['entry']], path)
    for key, value in (('description', description), ('compatibility_notes', compatibility_notes),
                       ('installable', installable)):
        if value is not None:
            entry[key] = value
    for key in ('description', 'compatibility_notes'):
        require(key in entry, app_id, f'new entries require --{key.replace("_", "-")}')
    entry['source'] = {'repository': repository, 'commit': commit, 'path': path}
    entry['files'] = file_rows(package_files(files))
    if previous:
        old_version = tuple(map(int, previous['version'].split('.')))
        new_version = tuple(map(int, entry['version'].split('.')))
        require(new_version >= old_version, app_id, 'refusing a version downgrade')
        require(new_version != old_version or entry['files'] == previous['files'],
                app_id, 'source bytes changed: publish a new version')
    result = copy.deepcopy(catalog)
    result['apps'] = sorted([app for app in result['apps'] if app['id'] != app_id] + [entry],
                            key=lambda app: app['id'])
    validate_sources(result, repo, mappings)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT / 'apps.json')
    parser.add_argument('--repo', type=Path, default=ROOT, help='local Git object checkout')
    parser.add_argument('--source-repo', action='append', default=[], metavar='OWNER/REPO=PATH')
    parser.add_argument('--repository', required=True, help='GitHub owner/repository (publisher chosen)')
    parser.add_argument('--commit', required=True, help='full 40-character lowercase source commit SHA')
    parser.add_argument('--path', required=True, help='apps/slug or existing Apps/Legacy-Name')
    parser.add_argument('--app-id', help='required for an existing legacy entry; native IDs come from app.toml')
    parser.add_argument('--description', help='required when adding an app')
    parser.add_argument('--compatibility-notes', help='required when adding an app')
    availability = parser.add_mutually_exclusive_group()
    availability.add_argument('--installable', dest='installable', action='store_true', default=None)
    availability.add_argument('--no-installable', dest='installable', action='store_false')
    parser.add_argument('--write', action='store_true', help='atomically replace the catalog after validation')
    args = parser.parse_args(argv)
    try:
        catalog = load_json(args.catalog)
        result = update(catalog, repo=args.repo, mappings=source_repositories(args.source_repo),
                        repository=args.repository, commit=args.commit, path=args.path,
                        app_id=args.app_id, description=args.description,
                        compatibility_notes=args.compatibility_notes, installable=args.installable)
        if args.write:
            write_catalog(args.catalog, result)
            print(f'OK: updated {args.catalog}')
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except (Invalid, OSError, ValueError, RecursionError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
