"""Persistent path safety and standalone/managed storage contract."""
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage_paths import private_parent
import monitor


class PersistentPathTests(unittest.TestCase):
    def test_invalid_ancestors_and_files_never_mutate_outside_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            outside = root / 'outside'
            outside.mkdir(mode=0o700)
            link = root / 'linked'
            link.symlink_to(outside, target_is_directory=True)
            for path in (Path('relative/watch.json'), root / '../escape/watch.json',
                         link / 'nested/watch.json', root / 'bad\nname/watch.json'):
                with self.subTest(path=path), self.assertRaises(OSError):
                    private_parent(path)
            self.assertEqual(list(outside.iterdir()), [])
            target = outside / 'watch.json'
            target.write_bytes(b'keep')
            os.link(target, root / 'hardlink')
            with self.assertRaises(OSError):
                monitor.save_watch([], target)
            self.assertEqual(target.read_bytes(), b'keep')

    def test_private_data_roundtrip_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "owner's data é" / 'watch.json'
            self.assertEqual(monitor.load_watch(path), [])
            self.assertFalse(path.parent.exists())
            monitor.save_watch([], path)
            self.assertEqual(monitor.load_watch(path), [])
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            path.parent.chmod(0o755)
            before = path.read_bytes()
            with self.assertRaises(OSError):
                monitor.save_watch([], path)
            self.assertEqual(path.read_bytes(), before)
