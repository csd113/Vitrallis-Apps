"""Native manifest/catalog alternatives and a real fixture publication flow."""
import copy
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import catalog_lib as lib
import build_rust_app
import update_catalog

TARGET = 'armv7-unknown-linux-gnueabihf'
BINARY = f'bin/{TARGET}/app'


def elf():
    data = bytearray(128)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHI', data, 16, 3, 40, 1)
    struct.pack_into('<I', data, 36, 0x05000400)
    return bytes(data)


class NativeRustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'apps/native-rust'
        shutil.copytree(TOOLS.parent / 'examples/hello-rust', self.source)
        manifest = self.source / 'app.toml'
        manifest.write_text(manifest.read_text().replace('runtime = "python"\nentry = "main.py"',
            f'runtime = "rust"\n\n[binaries]\n{TARGET} = "{BINARY}"'))
        (self.source / 'main.py').unlink()
        (self.source / 'requirements.txt').unlink()
        path = self.source / BINARY
        path.parent.mkdir(parents=True)
        path.write_bytes(elf())
        path.chmod(0o755)

    def test_native_manifest_exact_alternative_and_elf_validation(self):
        files = lib.local_files(self.source)
        self.assertEqual(lib.manifest(files, 'native')['runtime'], 'rust')
        for change in [b'entry = "main.py"\n', b'unknown = true\n']:
            malformed = dict(files, **{'app.toml': change + files['app.toml']})
            with self.assertRaises(lib.Invalid): lib.manifest(malformed, 'native')
        for payload in [b'not-ELF', elf()[:30], elf()[:18] + b'\xb7\x00' + elf()[20:],
                        elf()[:36] + struct.pack('<I', 0x05000200) + elf()[40:]]:
            with self.subTest(payload=payload[:24]), self.assertRaises(lib.Invalid):
                lib.manifest(dict(files, **{BINARY: payload}), 'native')
        del files[BINARY]
        with self.assertRaises(lib.Invalid): lib.manifest(files, 'native')
        lib.manifest(files, 'source build only', allow_unbuilt=True)

    def test_mapping_rejects_paths_types_unknown_targets_and_duplicates(self):
        for binaries in [{}, {'mips': 'app'}, {TARGET: ['app']}, {TARGET: '../app'},
                         {TARGET: 'tests/app'}, {TARGET: 'bin/app', 'x86_64-unknown-linux-gnu': 'bin/app'}]:
            with self.subTest(binaries=binaries), self.assertRaises(lib.Invalid):
                lib.runtime_fields({'runtime': 'rust', 'binaries': binaries}, 'test')

    def test_native_publication_preview_and_schema_reject_mixed_runtime(self):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        git('add', '.')
        git('commit', '-qm', 'Native source fixture')
        commit = git('rev-parse', 'HEAD')
        result = update_catalog.update({'schema_version': 1, 'apps': []}, repo=self.root,
            mappings={}, repository='publisher/catalog', commit=commit, path='apps/native-rust',
            description='Native fixture', compatibility_notes='ARMv7 fixture only')
        app = result['apps'][0]
        self.assertEqual(app['binaries'], {TARGET: BINARY})
        self.assertNotIn('entry', app)
        self.assertFalse(app['installable'])
        lib.validate_sources(result, self.root, {})
        repeated = update_catalog.update(result, repo=self.root, mappings={}, repository='publisher/catalog',
            commit=commit, path='apps/native-rust')
        self.assertEqual(json.dumps(repeated), json.dumps(result))
        for mutation in [{'entry': 'main.py'}, {'runtime': 'python'}, {'binaries': {}}]:
            bad = copy.deepcopy(result)
            bad['apps'][0].update(mutation)
            with self.assertRaises(lib.Invalid): lib.catalog_metadata(bad)
        bad = copy.deepcopy(result)
        bad['apps'][0]['files'] = [row for row in bad['apps'][0]['files'] if row['path'] != BINARY]
        with self.assertRaises(lib.Invalid): lib.catalog_metadata(bad)

    def test_new_schema_keywords_validate_their_own_shape(self):
        for schema in [{'oneOf': []}, {'oneOf': {}}, {'not': []}, {'minProperties': True},
                       {'oneOf': [{'unsupported': True}]}]:
            with self.subTest(schema=schema), self.assertRaises(lib.Invalid): lib.check_schema(schema)

    def test_native_build_stages_only_complete_matching_targets(self):
        (self.source / BINARY).unlink()
        output = self.root / 'staged'
        def compiler(args, check):
            directory = Path(args[args.index('--target-dir') + 1]) / TARGET / 'release'
            directory.mkdir(parents=True)
            (directory / 'hello-vitrallis-rust').write_bytes(elf())
        with patch('build_rust_app.subprocess.run', side_effect=compiler):
            build_rust_app.build(self.source, output, [TARGET])
        self.assertEqual(lib.manifest(lib.local_files(output), output)['runtime'], 'rust')
        self.assertEqual((output / BINARY).stat().st_mode & 0o777, 0o755)
        with self.assertRaises(lib.Invalid):
            build_rust_app.build(self.source, self.root / 'wrong', ['x86_64-unknown-linux-gnu'])
