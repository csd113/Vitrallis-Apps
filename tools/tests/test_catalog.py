"""Contract and end-to-end publication tests; no network or user-repo commits."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog_lib as lib
import update_catalog

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'examples/hello-vitrallis'


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {'schema_version': 1, 'apps': [{
            'id': 'org.example.hello', 'name': 'Hello', 'version': '0.1.0',
            'description': 'Test metadata', 'runtime': 'python', 'entry': 'main.py',
            'permissions': {'network': False, 'audio': False, 'storage': False},
            'installable': False, 'compatibility_notes': 'Test only',
            'source': {'repository': 'publisher/catalog', 'commit': 'a'*40, 'path': 'apps/hello'},
            'files': [{'path': 'main.py', 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}]
        }]}
        self.app = self.catalog['apps'][0]

    def rejected(self, fragment=None):
        with self.assertRaises(lib.Invalid) as raised:
            lib.catalog_metadata(self.catalog)
        if fragment:
            self.assertIn(fragment, str(raised.exception))

    def test_catalog_and_schema(self):
        lib.catalog_metadata(self.catalog)
        self.assertEqual(self.catalog['schema_version'], 1)

    def test_publisher_neutral_and_native_path(self):
        self.app['source'].update(repository='another-owner/My_Apps', path='apps/my-app')
        lib.catalog_metadata(self.catalog)
        self.app['source']['repository'] = 'publisher/.github'
        lib.catalog_metadata(self.catalog)

    def test_duplicate_ids(self):
        self.catalog['apps'].append(copy.deepcopy(self.app))
        self.rejected('duplicate app ID')

    def test_unsorted_ids(self):
        other = copy.deepcopy(self.app)
        other['id'] = 'aa.example'
        self.catalog['apps'].append(other)
        self.rejected('sorted by ID')

    def test_malformed_ids_and_versions(self):
        for key, values in {'id': ['hello', 'io.Vitrallis.app', 'io.foo-bar', 'io..foo', '1.a', 'io.a\n'],
                            'version': ['v1.0.0', '01.0.0', '1.0', '1.0.0-beta', '1.0.0+build', 1]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    bad = copy.deepcopy(self.catalog)
                    bad['apps'][0][key] = value
                    with self.assertRaises(lib.Invalid):
                        lib.catalog_metadata(bad)

    def test_invalid_repositories_and_source_paths(self):
        for key, values in {'repository': ['https://github.com/a/b', '../repo', 'a/b/c', '-a/b', 'a-/b', 'a--b/c', 'a/..', 'a/b\n'],
                            'path': ['', 'apps/../bad', '/apps/foo', 'apps/Foo', 'apps/a--b', 'Apps/foo', 'Apps/Bitcoin-Dashboard', 'Apps/foo/bar'],
                            'commit': ['main', 'a'*39, 'A'*40, '0'*40+'\n']}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    bad = copy.deepcopy(self.catalog)
                    bad['apps'][0]['source'][key] = value
                    with self.assertRaises(lib.Invalid):
                        lib.catalog_metadata(bad)

    def test_entry_and_paths(self):
        for path in ['../foo.py', '/main.py', 'a//b', 'a/./b', 'a/../b', 'a\\b', 'a.py\n']:
            with self.subTest(path=path):
                bad = copy.deepcopy(self.catalog)
                bad['apps'][0]['entry'] = path
                with self.assertRaises(lib.Invalid):
                    lib.catalog_metadata(bad)
        self.app['entry'] = 'missing.py'
        self.rejected('entry missing')

    def test_duplicate_case_collision_and_order(self):
        for paths in [['a', 'a'], ['A', 'a'], ['Assets/a', 'assets/b'], ['a', 'a/b'], ['b', 'a']]:
            with self.subTest(paths=paths), self.assertRaises(lib.Invalid):
                lib.check_paths(paths, 'test-app')

    def test_size_hash_types_and_limits(self):
        for field, values in {'size': [True, -1, lib.FILE_LIMIT+1, 1.5],
                              'sha256': ['x'*64, 'a'*63, 'A'*64, 1]}.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    bad = copy.deepcopy(self.catalog)
                    bad['apps'][0]['files'][0][field] = value
                    with self.assertRaises(lib.Invalid):
                        lib.catalog_metadata(bad)
        self.app['files'] = [{'path': f'{i}.py', 'size': lib.FILE_LIMIT, 'sha256': '0'*64}
                             for i in range(9)]
        self.app['entry'] = '0.py'
        self.rejected('bundle exceeds')

    def test_file_count_limit(self):
        self.app['files'] = [{'path': f'{i:03}.py', 'size': 0, 'sha256': '0'*64} for i in range(257)]
        self.rejected('item count')

    def test_controls_unknown_fields_and_wrong_types(self):
        self.app['description'] = 'unsafe\x85text'
        self.rejected('control characters')
        self.app['description'] = 'description'
        self.app['unexpected'] = 1
        self.rejected('unknown fields')
        del self.app['unexpected']
        self.catalog['schema_version'] = True
        self.rejected()

    def test_schema_evaluator_rejects_unknown_vocabulary(self):
        with self.assertRaises(lib.Invalid):
            lib.check_schema({'type': 'string', 'format': 'uri'})
        with self.assertRaises(lib.Invalid):
            lib.check_schema({'type': 'made-up'})
        with self.assertRaises(lib.Invalid):
            lib.check_schema({'type': 'string', 'pattern': '['})

    def test_duplicate_json_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'data.json'
            for value in ['{"apps": [], "apps": []}', '{"x": NaN}', '{"x": Infinity}']:
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(lib.Invalid):
                    lib.load_json(path)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.files = lib.local_files(EXAMPLE)

    def test_valid_example(self):
        self.assertEqual(lib.manifest(self.files, 'hello')['manifest_version'], 1)

    def test_missing_required_files_and_directories(self):
        for path in ['app.toml', 'main.py', 'icon.png', 'requirements.txt', 'README.md', 'CHANGELOG.md', 'assets/greeting.txt', 'tests/test_main.py']:
            files = dict(self.files)
            del files[path]
            with self.subTest(path=path), self.assertRaises(lib.Invalid):
                lib.manifest(files, 'hello')

    def test_invalid_manifest_fields(self):
        original = self.files['app.toml'].decode()
        for before, after in [('manifest_version = 1', 'manifest_version = 2'),
                              ('manifest_version = 1', 'manifest_version = true'),
                              ('manifest_version = 1', ''),
                              ('manifest_version = 1', 'manifest_version = 1\nfuture = true'),
                              ('manifest_version = 1', 'manifest_version = 1\nmanifest_version = 1'),
                              ('io.vitrallis.hello', 'io.Bad'),
                              ('0.1.0', '01.1.0'), ('python', 'shell'),
                              ('entry = "main.py"', 'entry = "../main.py"'),
                              ('entry = "main.py"', 'entry = "missing.py"'),
                              ('network = false', 'network = "false"'),
                              ('audio = false', 'audio = false\nmicrophone = false')]:
            files = dict(self.files, **{'app.toml': original.replace(before, after).encode()})
            with self.subTest(after=after), self.assertRaises(lib.Invalid):
                lib.manifest(files, 'hello')

    def test_corrupt_and_truncated_icon(self):
        for icon in [b'not a png', self.files['icon.png'][:-1], self.files['icon.png'] + b'extra']:
            files = dict(self.files, **{'icon.png': icon})
            with self.subTest(icon_length=len(icon)), self.assertRaises(lib.Invalid):
                lib.manifest(files, 'hello')
        icon = bytearray(self.files['icon.png'])
        icon[45] ^= 1
        with self.assertRaisesRegex(lib.Invalid, 'CRC'):
            lib.png_icon(bytes(icon), 'icon.png')

    def test_local_symlinks_fifos_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = root / 'package'
            shutil.copytree(EXAMPLE, package)
            link = package / 'link'
            link.symlink_to('main.py')
            with self.assertRaisesRegex(lib.Invalid, 'symlink'):
                lib.local_files(package)
            link.unlink()
            link.symlink_to('assets', target_is_directory=True)
            with self.assertRaisesRegex(lib.Invalid, 'symlink'):
                lib.local_files(package)
            link.unlink()
            os.mkfifo(link)
            with self.assertRaisesRegex(lib.Invalid, 'regular file'):
                lib.local_files(package)
            link.unlink()
            link.write_bytes(b'x' * (lib.FILE_LIMIT + 1))
            with self.assertRaisesRegex(lib.Invalid, 'exceeds'):
                lib.local_files(package)
            link.unlink()
            parent_link = root / 'parent-link'
            parent_link.symlink_to(package, target_is_directory=True)
            with self.assertRaisesRegex(lib.Invalid, 'symlink'):
                lib.local_files(parent_link)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        self.app = self.repo / 'apps/hello'
        shutil.copytree(EXAMPLE, self.app)
        self.run_git('init', '-q')
        self.run_git('config', 'user.name', 'Fixture')
        self.run_git('config', 'user.email', 'fixture@example.invalid')
        self.commit = self.commit_source()
        self.empty = {'schema_version': 1, 'apps': []}
        self.catalog = self.generate()

    def run_git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def commit_source(self):
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'Test fixture')
        return self.run_git('rev-parse', 'HEAD')

    def generate(self, **overrides):
        arguments = dict(repo=self.repo, mappings={}, repository='other-publisher/catalog',
                         commit=self.commit, path='apps/hello', description='Hello example',
                         compatibility_notes='Desktop only')
        arguments.update(overrides)
        return update_catalog.update(self.empty, **arguments)

    def test_packages_exclude_tests_but_validate_complete_source(self):
        files = lib.committed_files(self.repo, self.commit, 'apps/hello')
        self.assertIn('tests/test_main.py', files)
        paths = [row['path'] for row in self.catalog['apps'][0]['files']]
        self.assertNotIn('tests/test_main.py', paths)
        self.assertIn('main.py', paths)
        self.assertIn('assets/greeting.txt', paths)
        lib.validate_sources(self.catalog, self.repo, {})
        previous = copy.deepcopy(self.catalog)
        previous['apps'][0]['files'] = lib.file_rows(files)
        with self.assertRaisesRegex(lib.Invalid, 'excluding tests/'):
            lib.validate_sources(previous, self.repo, {})
        partial = copy.deepcopy(previous)
        partial['apps'][0]['files'] = [row for row in partial['apps'][0]['files']
                                      if row['path'] != 'main.py']
        with self.assertRaises(lib.Invalid):
            lib.validate_sources(partial, self.repo, {})

    def test_generated_catalog_valid_and_not_installable(self):
        lib.validate_sources(self.catalog, self.repo, {})
        entry = self.catalog['apps'][0]
        self.assertFalse(entry['installable'])
        self.assertEqual(entry['source']['repository'], 'other-publisher/catalog')
        self.assertEqual(entry['version'], '0.1.0')

    def test_bitcoin_uses_the_native_publication_contract(self):
        path = 'apps/bitcoin-dashboard'
        shutil.copytree(ROOT / path, self.repo / path)
        commit = self.commit_source()
        catalog = self.generate(commit=commit, path=path,
                                description='Bitcoin CAD price, chart, and network dashboard for the PocketCHIP.',
                                compatibility_notes='Requires Python 3.8+ and Tk 8.6; native integration pending.')
        lib.validate_sources(catalog, self.repo, {})
        entry = catalog['apps'][0]
        package = lib.manifest(lib.local_files(self.repo / path), path)
        for key in ('id', 'name', 'version', 'runtime', 'entry', 'permissions'):
            self.assertEqual(entry[key], package[key])
        self.assertEqual(entry['source']['path'], path)
        self.assertEqual(entry['source']['commit'], commit)
        self.assertFalse(entry['installable'])
        self.assertEqual(entry['files'], lib.file_rows(lib.package_files(lib.local_files(self.repo / path))))

    def test_dirty_and_staged_bytes_do_not_change_publication(self):
        (self.app / 'main.py').write_text('raise RuntimeError("dirty code must never run")')
        self.run_git('add', 'apps/hello/main.py')
        self.assertEqual(self.generate(), self.catalog)
        self.assertEqual(self.run_git('rev-parse', 'HEAD'), self.commit)

    def test_deterministic_cli_preview_write_and_repeat(self):
        target = self.repo / 'catalog.json'
        target.write_text(json.dumps(self.empty))
        command = [sys.executable, str(ROOT / 'tools/update_catalog.py'), '--catalog', str(target),
                   '--repo', str(self.repo), '--repository', 'other-publisher/catalog',
                   '--commit', self.commit, '--path', 'apps/hello', '--description', 'Hello example',
                   '--compatibility-notes', 'Desktop only']
        before = target.read_bytes()
        preview = subprocess.run(command, capture_output=True, check=True)
        self.assertEqual(target.read_bytes(), before)
        subprocess.run(command + ['--write'], capture_output=True, check=True)
        self.assertEqual(target.read_bytes(), preview.stdout)
        subprocess.run(command + ['--write'], capture_output=True, check=True)
        self.assertEqual(target.read_bytes(), preview.stdout)

    def test_failed_cli_write_preserves_catalog(self):
        target = self.repo / 'catalog.json'
        target.write_text(json.dumps(self.empty))
        original = target.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'tools/update_catalog.py'),
                                 '--catalog', str(target), '--repo', str(self.repo),
                                 '--repository', 'other-publisher/catalog', '--commit', self.commit,
                                 '--path', 'apps/missing', '--write'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(target.read_bytes(), original)

    def test_symlink_output_and_failed_replace_preserve_original(self):
        target = self.repo / 'catalog.json'
        target.write_text(json.dumps(self.empty))
        original = target.read_bytes()
        link = self.repo / 'link.json'
        link.symlink_to(target.name)
        with self.assertRaises(lib.Invalid):
            lib.write_catalog(link, self.catalog)
        with patch.object(lib.os, 'replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                lib.write_catalog(target, self.catalog)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.repo.glob('.catalog-*')), [])

    def test_missing_commit_path_and_non_commit_object(self):
        blob = self.run_git('rev-parse', f'{self.commit}:apps/hello/main.py')
        for commit, path in [('0'*40, 'apps/hello'), (self.commit, 'apps/missing'),
                             (blob, 'apps/hello'), ('HEAD', 'apps/hello')]:
            with self.subTest(commit=commit, path=path), self.assertRaises(lib.Invalid):
                lib.committed_files(self.repo, commit, path)

    def test_missing_extra_files_hash_and_size_mismatch(self):
        for change in ['missing', 'extra', 'hash', 'size']:
            catalog = copy.deepcopy(self.catalog)
            rows = catalog['apps'][0]['files']
            if change == 'missing':
                rows.pop()
            elif change == 'extra':
                rows.append({'path': 'zzz', 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()})
            elif change == 'hash':
                rows[0]['sha256'] = '0'*64
            else:
                rows[0]['size'] += 1
            with self.subTest(change=change), self.assertRaises(lib.Invalid):
                lib.validate_sources(catalog, self.repo, {})

    def test_manifest_catalog_consistency(self):
        for key, value in [('version', '9.0.0'), ('id', 'other.id'), ('name', 'Other'),
                           ('permissions', {'network': True, 'audio': False, 'storage': False})]:
            catalog = copy.deepcopy(self.catalog)
            catalog['apps'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(lib.Invalid, 'catalog/manifest mismatch'):
                lib.validate_sources(catalog, self.repo, {})

    def test_symlink_and_submodule_in_commit(self):
        link = self.app / 'link'
        link.symlink_to('main.py')
        commit = self.commit_source()
        with self.assertRaisesRegex(lib.Invalid, 'unsafe file type'):
            lib.committed_files(self.repo, commit, 'apps/hello')
        link.unlink()
        self.run_git('add', '-u')
        self.run_git('update-index', '--add', '--cacheinfo', f'160000,{self.commit},apps/hello/submodule')
        self.run_git('commit', '-qm', 'Submodule fixture')
        with self.assertRaisesRegex(lib.Invalid, 'unsafe file type'):
            lib.committed_files(self.repo, self.run_git('rev-parse', 'HEAD'), 'apps/hello')

    def test_symlink_source_directory(self):
        (self.repo / 'apps/linked').symlink_to('hello', target_is_directory=True)
        commit = self.commit_source()
        with self.assertRaises(lib.Invalid):
            lib.committed_files(self.repo, commit, 'apps/linked')

    def test_same_version_changes_and_downgrades_refused(self):
        self.empty = self.catalog
        (self.app / 'assets/greeting.txt').write_text('Changed greeting')
        new_commit = self.commit_source()
        with self.assertRaisesRegex(lib.Invalid, 'publish a new version'):
            self.generate(commit=new_commit)
        manifest = self.app / 'app.toml'
        manifest.write_text(manifest.read_text().replace('0.1.0', '0.0.9'))
        (self.app / 'CHANGELOG.md').write_text('# Changelog\n\n## 0.0.9 — 2026-09-12\n\n- Test the refused version downgrade.\n')
        new_commit = self.commit_source()
        with self.assertRaisesRegex(lib.Invalid, 'downgrade'):
            self.generate(commit=new_commit)
        manifest.write_text(manifest.read_text().replace('0.0.9', '0.2.0'))
        (self.app / 'CHANGELOG.md').write_text('# Changelog\n\n## 0.2.0 — 2026-09-12\n\n- Change the greeting asset in this release.\n')
        new_commit = self.commit_source()
        result = self.generate(commit=new_commit)
        self.assertEqual(result['apps'][0]['version'], '0.2.0')

    def test_source_mapping(self):
        lib.validate_sources(self.catalog, self.repo / 'missing',
                             {'other-publisher/catalog': self.repo})
        with self.assertRaises(lib.Invalid):
            lib.source_repositories(['bad-value'])
        with self.assertRaises(lib.Invalid):
            lib.source_repositories(['a/b=x', 'a/b=y'])

    def test_replace_objects_are_ignored(self):
        (self.app / 'assets/greeting.txt').write_text('replacement')
        replacement = self.commit_source()
        self.run_git('replace', self.commit, replacement)
        self.assertEqual(self.generate(), self.catalog)

    def test_committed_bundle_limits(self):
        for limit_name, limit, message in [('FILE_LIMIT', 1, 'file exceeds'),
                                            ('BUNDLE_LIMIT', 1, 'bundle exceeds'),
                                            ('FILE_COUNT', 1, 'files')]:
            with self.subTest(limit=limit_name), patch.object(lib, limit_name, limit):
                with self.assertRaisesRegex(lib.Invalid, message):
                    lib.committed_files(self.repo, self.commit, 'apps/hello')

    def test_committed_case_collision_and_missing_native_manifest(self):
        # Construct the extra entry in the index so this also tests macOS, where
        # the working filesystem may not store both casings simultaneously.
        blob = self.run_git('rev-parse', f'{self.commit}:apps/hello/assets/greeting.txt')
        self.run_git('update-index', '--add', '--cacheinfo', f'100644,{blob},apps/hello/Assets/other.txt')
        self.run_git('commit', '-qm', 'Case collision fixture')
        with self.assertRaisesRegex(lib.Invalid, 'case-colliding'):
            lib.committed_files(self.repo, self.run_git('rev-parse', 'HEAD'), 'apps/hello')
        self.run_git('update-index', '--force-remove', 'apps/hello/Assets/other.txt')
        (self.app / 'app.toml').unlink()
        commit = self.commit_source()
        with self.assertRaisesRegex(lib.Invalid, 'missing package files'):
            self.generate(commit=commit)

    def test_manifest_required_even_with_literal_python_version(self):
        (self.app / 'app.toml').unlink()
        (self.app / 'main.py').write_text('VERSION = "0.1.0"\nraise RuntimeError()\n')
        commit = self.commit_source()
        with self.assertRaisesRegex(lib.Invalid, 'missing package files'):
            self.generate(commit=commit)
        catalog = copy.deepcopy(self.catalog)
        catalog['apps'][0]['source']['commit'] = commit
        files = lib.committed_files(self.repo, commit, 'apps/hello')
        catalog['apps'][0]['files'] = lib.file_rows(lib.package_files(files))
        with self.assertRaisesRegex(lib.Invalid, 'missing package files'):
            lib.validate_sources(catalog, self.repo, {})

    def test_source_path_rejected_before_git_access(self):
        with patch.object(lib, 'git', side_effect=AssertionError('unexpected Git access')):
            with self.assertRaises(lib.Invalid):
                self.generate(path='Apps/Bitcoin-Dashboard')


if __name__ == '__main__':
    unittest.main()
