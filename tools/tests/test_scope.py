import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scoped_tests as test_scope


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ('one', 'two'):
            directory = self.root / 'apps' / name
            directory.mkdir(parents=True)
            (directory / 'app.toml').write_text('')
            (directory / 'main.py').write_text('')

    def test_single_app_and_documentation_assets(self):
        self.assertEqual(test_scope.select(self.root, ['apps/one/main.py']), ['apps/one'])
        for path in ('README.md', 'apps/one/README.md', 'apps/one/icon.png', 'apps/one/app.toml'):
            self.assertEqual(test_scope.select(self.root, [path]), [])
        self.assertEqual(test_scope.select(self.root, ['apps/one/requirements.txt']), ['apps/one'])
        self.assertEqual(test_scope.select(self.root, ['apps/one/tests/test_ui.py']), ['apps/one'])

    def test_transitive_shared_import_only_selects_dependents(self):
        (self.root / 'shared.py').write_text('import helper\n')
        (self.root / 'helper.py').write_text('')
        (self.root / 'apps/one/main.py').write_text('import shared\n')
        self.assertEqual(test_scope.select(self.root, ['helper.py']), ['apps/one'])
        self.assertEqual(test_scope.select(self.root, ['tools/validate_catalog.py']), [])
        (self.root / 'helper.py').unlink()
        self.assertEqual(test_scope.select(self.root, ['helper.py']), ['apps/one'])
        self.assertEqual(test_scope.select(self.root, ['apps/two/assets/data.txt']), ['apps/two'])

    def test_declared_dynamic_and_cargo_dependencies(self):
        shared = self.root / 'shared'
        shared.mkdir()
        (self.root / 'apps/one/test-dependencies.json').write_text(json.dumps(['shared']))
        (self.root / 'apps/two/Cargo.toml').write_text('[dependencies]\nshared = {path = "../../shared"}\n')
        self.assertEqual(test_scope.select(self.root, ['shared/runtime.rs']), ['apps/one', 'apps/two'])

    def test_relative_import_and_transitive_cargo_paths(self):
        sub = self.root / 'apps/one/sub'
        sub.mkdir()
        (sub / 'module.py').write_text('from .. import helper\n')
        (self.root / 'apps/one/helper.py').write_text('import shared\n')
        (self.root / 'shared.py').write_text('')
        self.assertEqual(test_scope.select(self.root, ['shared.py']), ['apps/one'])
        for name in ('shared', 'core'):
            (self.root / name).mkdir()
        (self.root / 'apps/two/Cargo.toml').write_text('[dependencies]\nshared = {path = "../../shared"}\n')
        (self.root / 'shared/Cargo.toml').write_text('[dependencies]\ncore = {path = "../core"}\n')
        self.assertEqual(test_scope.select(self.root, ['core/lib.rs']), ['apps/two'])

    def test_dependency_configuration_and_symlinks_fail_closed(self):
        declaration = self.root / 'apps/one/test-dependencies.json'
        for value in ({'apps': True}, ['../outside'], [42], 'apps'):
            declaration.write_text(json.dumps(value))
            with self.assertRaises(ValueError): test_scope.select(self.root, ['shared.py'])
        declaration.unlink()
        source = self.root / 'apps/one/main.py'
        source.unlink()
        source.symlink_to(self.root / 'apps/two/main.py')
        with self.assertRaises(ValueError): test_scope.select(self.root, ['shared.py'])

    def test_explicit_selection_and_bad_input_fail_closed(self):
        self.assertEqual(test_scope.select(self.root, [], ['apps/two']), ['apps/two'])
        for changes, apps in [(['../outside'], []), ([], ['apps/missing'])]:
            with self.assertRaises(ValueError):
                test_scope.select(self.root, changes, apps)
        (self.root / 'apps/one/main.py').write_text('invalid python !')
        with self.assertRaises(SyntaxError):
            test_scope.select(self.root, ['shared.py'])
