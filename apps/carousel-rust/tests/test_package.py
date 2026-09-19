"""Package and shared-contract checks, runnable by the existing Python CI loop."""
import pathlib
import sys
import tomllib
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from catalog_lib import local_files, manifest


class PackageTests(unittest.TestCase):
    def test_native_package_and_version(self):
        data = manifest(local_files(PACKAGE), PACKAGE)
        self.assertEqual(data['runtime'], 'rust')
        self.assertNotIn('entry', data)
        self.assertEqual(data['name'], 'Carousel-Rust')
        cargo = tomllib.loads((PACKAGE / 'Cargo.toml').read_text())
        self.assertEqual(cargo['package']['version'], data['version'])
        self.assertFalse((PACKAGE / 'main.py').exists())

    def test_browser_contract_matches_python(self):
        original = ROOT / 'apps/vitrallis-media-carousel/web'
        for filename in ('app.js', 'index.html', 'style.css'):
            self.assertEqual((PACKAGE / 'web' / filename).read_bytes(), (original / filename).read_bytes())
        self.assertIn('io.vitrallis.mediacarousel', (PACKAGE / 'src/storage.rs').read_text())

    def test_keyboard_regressions_are_packaged_as_development_tests(self):
        source = (PACKAGE / 'tests/unit.rs').read_text()
        self.assertIn('keyboard_baseline_and_authenticated_management_round_trip', source)
        self.assertIn('shared_flock_blocks_python_and_second_rust_writer', source)
        self.assertIn('Escape', (PACKAGE / 'README.md').read_text())
