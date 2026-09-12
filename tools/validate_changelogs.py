#!/usr/bin/env python3
"""Check release histories and, with --base, enforce the app submission policy."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from catalog_lib import (CATALOG_LIMIT, COMMIT, FILE_LIMIT, ID, ROOT, SOURCE_PATH,
                         VERSION, Invalid, app_changelog, catalog_metadata,
                         committed_files, file_rows, git, manifest, match,
                         package_files, release_date, release_summary, require,
                         safe_path, source_repositories, unique_object,
                         reject_constant, validate_sources)


def git_file(repo, commit, path, limit=FILE_LIMIT):
    """Read one bounded regular blob, treating only an absent path as missing."""
    match(commit, COMMIT, 'commit')
    safe_path(path, 'Git path')
    records = git(repo, 'ls-tree', '-z', commit, '--', path).split(b'\0')
    records = [record for record in records if record]
    if not records:
        return None
    require(len(records) == 1, path, 'expected one Git blob')
    header, name = records[0].split(b'\t', 1)
    mode, kind, oid = header.decode('ascii').split()
    require(name.decode('ascii') == path and mode in ('100644', '100755') and kind == 'blob',
            path, 'expected a regular file, not a symlink or directory')
    require(int(git(repo, 'cat-file', '-s', oid)) <= limit, path, 'file exceeds size limit')
    return git(repo, 'cat-file', 'blob', oid)


def catalog_at(repo, commit):
    raw = git_file(repo, commit, 'apps.json', CATALOG_LIMIT)
    require(raw is not None, commit, 'missing apps.json')
    catalog = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    catalog_metadata(catalog)
    return catalog


def catalog_history(raw):
    require(raw is not None, 'CHANGELOG.md', 'missing catalog changelog')
    entries = {}
    day = None
    days = []
    for line in raw.decode('utf-8').splitlines():
        if line.startswith('## '):
            day = release_date(line[3:], 'CHANGELOG.md')
            days.append(day)
        elif line.startswith(('- Added', '- Updated')):
            item = re.fullmatch(rf'- (Added|Updated) `({ID})` `({VERSION})`: (.+)', line)
            require(item is not None and day is not None, 'CHANGELOG.md',
                    'use a dated section and: - Added|Updated `APP_ID` `VERSION`: concrete summary')
            action, app_id, version, summary = item.groups()
            match(app_id, ID, 'CHANGELOG.md app ID', 128)
            match(version, VERSION, 'CHANGELOG.md version', 32)
            release_summary(summary, 'CHANGELOG.md')
            key = (app_id, version)
            require(key not in entries, 'CHANGELOG.md', f'duplicate release {app_id} {version}')
            entries[key] = (action, day, summary)
    require(days == sorted(days, reverse=True), 'CHANGELOG.md', 'dates must be newest first')
    return entries


def packages_at(repo, commit):
    records = git(repo, 'ls-tree', '-z', commit, '--', 'apps').split(b'\0')
    if not records[0]:
        return {}
    require(records[0].startswith(b'040000 tree '), 'apps', 'expected a regular directory')
    result = {}
    for record in git(repo, 'ls-tree', '-z', f'{commit}:apps').split(b'\0'):
        if not record:
            continue
        header, name = record.split(b'\t', 1)
        path = 'apps/' + name.decode('ascii')
        match(path, SOURCE_PATH, path, 240)
        require(header.startswith(b'040000 tree '), path, 'expected a regular app directory')
        result[path] = committed_files(repo, commit, path)
    return result


def check(repo, head, base=None, mappings=None):
    mappings = mappings or {}
    for commit in (head, base):
        if commit is not None:
            match(commit, COMMIT, 'commit')
            require(git(repo, 'cat-file', '-t', commit).strip() == b'commit', commit,
                    'expected a full commit SHA')
    if base is not None:
        require(git(repo, 'merge-base', base, head).decode().strip() == base,
                '--base', 'must be an ancestor of the checked head')
    catalog = catalog_at(repo, head)
    validate_sources(catalog, repo, mappings)
    history = catalog_history(git_file(repo, head, 'CHANGELOG.md'))
    packages = packages_at(repo, head)
    listed = {app['id']: app for app in catalog['apps']}
    manifests = {}
    for path, files in packages.items():
        package = manifest(files, path)
        app_id = package['id']
        require(app_id not in manifests, path, 'duplicate app identity')
        manifests[app_id] = package
        require(app_id in listed, path, 'submitted app must be listed in apps.json')
        entry = listed[app_id]
        require(entry['source']['path'] == path and entry['files'] == file_rows(package_files(files)),
                path, 'apps.json must publish the current package bytes and version')
    for app in catalog['apps']:
        key = (app['id'], app['version'])
        require(key in history, app['id'], 'catalog changelog is missing this release')
        files = committed_files(mappings.get(app['source']['repository'], repo),
                                app['source']['commit'], app['source']['path'])
        notes = app_changelog(files['CHANGELOG.md'], app['version'], app['id'])
        require(history[key][1] >= notes[app['version']][0], app['id'],
                'catalog publication date precedes the app release date')
    if base is not None:
        check_changes(repo, base, catalog, packages, history)
    return len(catalog['apps'])


def check_changes(repo, base, catalog, packages, history):
    previous_catalog = catalog_at(repo, base)
    previous = {app['id']: app for app in previous_catalog['apps']}
    old_raw = git_file(repo, base, 'CHANGELOG.md')
    old_history = catalog_history(old_raw) if old_raw is not None else {}
    for key, entry in old_history.items():
        require(history.get(key) == entry, 'CHANGELOG.md', f'preserve published history for {key}')
    changed = set()
    for app in catalog['apps']:
        old = previous.get(app['id'])
        key = (app['id'], app['version'])
        if old is None or old['version'] != app['version']:
            if old is not None:
                require(version_key(app['version']) > version_key(old['version']), app['id'],
                        'catalog version downgrades are forbidden')
            require(key not in old_history and history[key][0] == ('Added' if old is None else 'Updated'),
                    app['id'], 'new releases need a new matching Added/Updated catalog entry')
            changed.add(key)
        elif old['files'] != app['files']:
            raise Invalid(f"{app['id']}: changed package bytes require a new version")
    if old_raw is not None:
        require(set(history) - set(old_history) == changed, 'CHANGELOG.md',
                'new catalog release entries must match added or updated catalog versions')
    old_packages = packages_at(repo, base)
    for path, files in packages.items():
        old_files = old_packages.get(path)
        if old_files is None:
            continue
        current = manifest(files, path)
        # The previous commit may predate changelog adoption; read its manifest
        # as data so bootstrap releases can add the newly required file.
        old = tomllib.loads(old_files['app.toml'].decode('utf-8'))
        require(current['id'] == old['id'], path, 'preserve the existing app ID')
        if package_files(files) != package_files(old_files):
            require(version_key(current['version']) > version_key(old['version']), path,
                    'changed package bytes require a higher manifest version')
        if old_raw is not None:
            before = app_changelog(old_files['CHANGELOG.md'], old['version'], path)
            after = app_changelog(files['CHANGELOG.md'], current['version'], path)
            for version, entry in before.items():
                require(after.get(version) == entry, path,
                        f'preserve published changelog entry {version}')


def version_key(version):
    match(version, VERSION, 'version', 32)
    return tuple(map(int, version.split('.')))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--head', help='full commit SHA; defaults to HEAD')
    parser.add_argument('--base', help='full ancestor commit SHA for merge-policy checks')
    parser.add_argument('--source-repo', action='append', default=[], metavar='OWNER/REPO=PATH')
    args = parser.parse_args(argv)
    try:
        head = args.head or git(args.repo, 'rev-parse', 'HEAD').decode().strip()
        count = check(args.repo, head, args.base, source_repositories(args.source_repo))
        print(f'OK: changelog policy ({count} published apps; histories and versions verified)')
    except (Invalid, OSError, ValueError, KeyError, UnicodeError, RecursionError,
            subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
