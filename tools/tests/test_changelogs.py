"""Release-policy regressions using disposable Git repositories; no network."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog_lib as lib
import update_catalog
import validate_changelogs as policy

ROOT = Path(__file__).resolve().parents[2]
DAY = '2026-09-12'


class ChangelogTests(unittest.TestCase):
    def test_valid_dated_release_and_concrete_notes(self):
        notes = lib.app_changelog(b'# Changelog\n\n## 1.0.0 \xe2\x80\x94 2026-09-12\n\n- Add keyboard navigation to the viewer.\n', '1.0.0', 'app')
        self.assertEqual(str(notes['1.0.0'][0]), DAY)

    def test_invalid_or_placeholder_app_entries(self):
        valid = f'# Changelog\n\n## 1.0.0 — {DAY}\n\n- Add keyboard navigation to the viewer.\n'
        for bad in [valid.replace(DAY, '2026-02-30'), valid.replace(f' — {DAY}', ''),
                    valid.replace('1.0.0', '0.9.0'), valid.replace('- Add keyboard navigation to the viewer.', ''),
                    valid.replace('Add keyboard navigation to the viewer.', 'TODO: describe this release.'),
                    valid.replace('Add keyboard navigation to the viewer.', 'Updated.'),
                    valid + valid, valid + valid.replace('1.0.0', '2.0.0'),
                    valid + valid.replace('1.0.0', '0.9.0').replace(DAY, '2026-09-13')]:
            with self.subTest(bad=bad), self.assertRaises(lib.Invalid):
                lib.app_changelog(bad.encode(), '1.0.0', 'app')
        with self.assertRaises(lib.Invalid):
            lib.app_changelog(b'\xff', '1.0.0', 'app')

    def test_catalog_entries_need_dates_id_version_and_summary(self):
        valid = f'# Catalog changelog\n\n## {DAY}\n\n- Added `org.example.app` `1.0.0`: Add a native image viewer.\n'
        self.assertEqual(policy.catalog_history(valid.encode())[('org.example.app', '1.0.0')][0], 'Added')
        for bad in [valid.replace(f'## {DAY}\n', ''), valid.replace(DAY, '2026-13-01'),
                    valid.replace('`1.0.0`', 'latest'), valid.replace('org.example.app', '../app'),
                    valid.replace('Add a native image viewer.', 'TBD describe changes'),
                    valid + valid, valid + '\n## 2026-09-13\n']:
            with self.subTest(bad=bad), self.assertRaises(lib.Invalid):
                policy.catalog_history(bad.encode())


class MergePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.app = self.repo / 'apps/hello'
        shutil.copytree(ROOT / 'examples/hello-vitrallis', self.app)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.catalog = {'schema_version': 1, 'apps': []}
        self.write_json(self.catalog)
        self.history = self.repo / 'CHANGELOG.md'
        self.history.write_text(f'# Catalog changelog\n\n## {DAY}\n\n- Added `io.vitrallis.hello` `0.1.0`: Add an offline greeting app.\n')
        source = self.commit()
        self.catalog = update_catalog.update(self.catalog, repo=self.repo, mappings={},
            repository='example/catalog', commit=source, path='apps/hello',
            description='A greeting app.', compatibility_notes='Fixture only')
        self.write_json(self.catalog)
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Release policy fixture')
        return self.git('rev-parse', 'HEAD')

    def write_json(self, catalog):
        (self.repo / 'apps.json').write_text(json.dumps(catalog, indent=2) + '\n')

    def prepare_update(self, version='0.2.0'):
        path = self.app / 'app.toml'
        path.write_text(path.read_text().replace('0.1.0', version))
        path = self.app / 'CHANGELOG.md'
        path.write_text(path.read_text().replace('## 0.1.0', f'## {version} — {DAY}\n\n- Add a personalized greeting to the app.\n\n## 0.1.0', 1))
        self.history.write_text(self.history.read_text().replace('- Added',
            f'- Updated `io.vitrallis.hello` `{version}`: Add a personalized greeting to the app.\n- Added', 1))

    def publish(self):
        """Construct exact inventories even for deliberately invalid test inputs."""
        source = self.commit()
        files = lib.committed_files(self.repo, source, 'apps/hello')
        manifest = tomllib.loads(files['app.toml'].decode())
        app = self.catalog['apps'][0]
        app.update({key: manifest[key] for key in ('id', 'name', 'version', 'runtime', 'entry', 'permissions')})
        app['source']['commit'] = source
        app['files'] = lib.file_rows(lib.package_files(files))
        self.write_json(self.catalog)
        return self.commit()

    def rejected(self, message, head=None):
        with self.assertRaisesRegex(lib.Invalid, message):
            policy.check(self.repo, head or self.git('rev-parse', 'HEAD'), self.base)

    def test_current_catalog_and_complete_update_pass(self):
        self.assertEqual(policy.check(self.repo, self.base), 1)
        self.prepare_update()
        self.assertEqual(policy.check(self.repo, self.publish(), self.base), 1)

    def test_new_app_requires_added_entry(self):
        new = self.repo / 'apps/second'
        shutil.copytree(self.app, new)
        path = new / 'app.toml'
        path.write_text(path.read_text().replace('io.vitrallis.hello', 'org.example.second'))
        source = self.commit()
        self.catalog = update_catalog.update(self.catalog, repo=self.repo, mappings={},
            repository='example/catalog', commit=source, path='apps/second',
            description='A second greeting app.', compatibility_notes='Fixture only')
        self.write_json(self.catalog)
        self.commit()
        self.rejected('missing this release')
        self.history.write_text(self.history.read_text() + '- Added `org.example.second` `0.1.0`: Add the second greeting app.\n')
        self.assertEqual(policy.check(self.repo, self.commit(), self.base), 2)

    def test_missing_app_changelog_fails_package_publication(self):
        (self.app / 'CHANGELOG.md').unlink()
        self.publish()
        self.rejected('missing package files')

    def test_version_bump_without_matching_app_entry_fails(self):
        path = self.app / 'app.toml'
        path.write_text(path.read_text().replace('0.1.0', '0.2.0'))
        self.publish()
        self.rejected('newest changelog entry')

    def test_missing_catalog_changelog_and_release_entry_fail(self):
        self.prepare_update()
        self.history.write_text(self.history.read_text().replace('- Updated', '- Untracked'))
        self.publish()
        self.rejected('missing this release')
        self.history.unlink()
        self.commit()
        self.rejected('missing catalog changelog')

    def test_update_cannot_be_labelled_added(self):
        self.prepare_update()
        self.history.write_text(self.history.read_text().replace('- Updated', '- Added'))
        self.publish()
        self.rejected('matching Added/Updated')

    def test_changed_shipped_bytes_require_higher_version(self):
        (self.app / 'assets/greeting.txt').write_text('Changed without bumping version')
        self.publish()
        self.rejected('require a new version')

    def test_source_update_with_stale_catalog_is_rejected(self):
        self.prepare_update()
        self.commit()
        self.rejected('current package bytes and version')

    def test_test_only_changes_do_not_require_release(self):
        (self.app / 'tests/release_test.txt').write_text('Additional development-only coverage')
        self.assertEqual(policy.check(self.repo, self.commit(), self.base), 1)

    def test_old_catalog_history_cannot_be_deleted_or_changed(self):
        self.history.write_text(self.history.read_text().replace('Add an offline greeting app.', 'Rewrite the initial release summary.'))
        self.commit()
        self.rejected('preserve published history')

    def test_old_app_history_is_preserved_on_update(self):
        self.prepare_update()
        path = self.app / 'CHANGELOG.md'
        path.write_text(path.read_text().replace('offline greeting window', 'rewritten historical window'))
        self.publish()
        self.rejected('preserve published changelog entry')

    def test_invented_catalog_release_is_rejected(self):
        self.history.write_text(self.history.read_text() + '- Updated `io.vitrallis.hello` `9.0.0`: Invent an unpublished future release.\n')
        self.commit()
        self.rejected('must match added or updated')

    def test_publication_date_cannot_precede_app_release(self):
        self.prepare_update()
        self.history.write_text(self.history.read_text().replace(DAY, '2026-09-11'))
        self.publish()
        self.rejected('publication date precedes')

    def test_unsafe_history_paths_and_commits_fail_closed(self):
        self.history.unlink()
        self.history.symlink_to('apps/hello/CHANGELOG.md')
        self.commit()
        self.rejected('regular file')
        with self.assertRaises(lib.Invalid):
            policy.check(self.repo, '--help', self.base)
        with self.assertRaises(lib.Invalid):
            policy.check(self.repo, self.git('rev-parse', 'HEAD:apps'), self.base)

    def test_cli_rejects_failed_check_without_traceback_or_mutation(self):
        self.prepare_update()
        head = self.commit()
        before = (self.repo / 'apps.json').read_bytes()
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/validate_changelogs.py'),
            '--repo', str(self.repo), '--base', self.base, '--head', head], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('ERROR:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual((self.repo / 'apps.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
