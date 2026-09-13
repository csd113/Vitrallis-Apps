import json
import os
from pathlib import Path
from unittest.mock import patch

from support import StorageCase
from library import Library, display_name, identifier
from settings import DEFAULTS, Settings, validate
from storage import InstanceLock, Paths, atomic_json, read_json, regular_open


class SettingsTests(StorageCase):
    def test_defaults_do_not_write_settings_on_read(self):
        self.assertEqual(self.settings.snapshot(), DEFAULTS)
        self.assertFalse(self.settings.path.exists())

    def test_persistence_and_no_redundant_write(self):
        value = dict(DEFAULTS, image_seconds=8, order="shuffle", loop=False)
        self.settings.save(value)
        self.assertEqual(Settings(self.paths.config).snapshot(), value)
        with patch("settings.atomic_json", side_effect=AssertionError("Unnecessary write")):
            self.settings.save(value)

    def test_corrupt_settings_recover_without_destroying_evidence(self):
        for raw in (b"{broken", b"[]", b'{"image_seconds":true}', b'{"image_seconds":NaN}'):
            self.settings.path.write_bytes(raw)
            recovered = Settings(self.paths.config)
            self.assertEqual(recovered.snapshot(), DEFAULTS)
            self.assertTrue(recovered.warning)
            self.assertEqual(recovered.path.read_bytes(), raw)
        recovered.save(DEFAULTS)
        self.assertFalse(recovered.warning)

    def test_invalid_numeric_and_enum_settings(self):
        for key, values in {"image_seconds": [True, 0, 3601, 1.5, "3"], "repeats": [False, 0, 101],
                            "order": ["random", None], "loop": [1, "yes"]}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate(dict(DEFAULTS, **{key: value}))

    def test_failed_setting_write_preserves_disk_and_memory(self):
        self.settings.save(DEFAULTS)
        before = self.settings.path.read_bytes()
        with patch("storage.os.replace", side_effect=OSError("power interruption")), self.assertRaises(OSError):
            self.settings.save(dict(DEFAULTS, repeats=7))
        self.assertEqual(self.settings.snapshot(), DEFAULTS)
        self.assertEqual(self.settings.path.read_bytes(), before)
        self.assertEqual(list(self.paths.config.glob(".write-*")), [])


class LibraryTests(StorageCase):
    def test_default_create_rename_duplicate_names_and_persistence(self):
        self.assertEqual(self.library.snapshot()[0]["name"], "Unsorted")
        row = self.library.create("  Weekend café  ")
        self.assertEqual(row["name"], "Weekend café")
        with self.assertRaises(ValueError):
            self.library.create("WEEKEND CAFÉ")
        self.library.rename(row["id"], "Favorites")
        restored = Library(self.paths)
        self.assertEqual(restored.snapshot()[1]["name"], "Favorites")
        with self.assertRaises(ValueError):
            restored.rename(row["id"], "Unsorted")

    def test_duplicate_filenames_have_unique_ids(self):
        a, b = self.add(), self.add()
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(a["name"], b["name"])

    def test_saved_order_and_snapshot_independence(self):
        a, b, c = self.add(), self.add("b.png"), self.add("c.png")
        snapshot = self.library.playlist(self.cid)
        self.library.reorder(self.cid, [c["id"], a["id"], b["id"]])
        self.assertEqual([item["id"] for item in Library(self.paths).playlist(self.cid)], [c["id"], a["id"], b["id"]])
        self.assertEqual([item["id"] for item in snapshot], [a["id"], b["id"], c["id"]])
        with self.assertRaises(ValueError):
            self.library.reorder(self.cid, [a["id"], a["id"], c["id"]])

    def test_file_and_collection_deletion_and_last_default(self):
        item = self.add()
        self.library.delete(self.cid, item["id"])
        self.assertEqual(self.library.playlist(self.cid), [])
        self.assertFalse((self.paths.media / item["id"]).exists())
        self.library.delete(self.cid)
        self.assertEqual(self.library.snapshot()[0]["name"], "Unsorted")
        self.assertNotEqual(self.library.snapshot()[0]["id"], self.cid)

    def test_delete_commit_failure_keeps_media(self):
        item = self.add()
        before = self.library.path.read_bytes()
        with patch("storage.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.library.delete(self.cid)
        self.assertEqual(self.library.path.read_bytes(), before)
        self.assertTrue((self.paths.media / item["id"]).exists())

    def test_upload_metadata_failure_removes_unreferenced_destination(self):
        stream, path = self.library.temporary_upload()
        with stream:
            stream.write(b"data")
        with patch("library.atomic_json", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.library.add_upload(self.cid, "x.png", path, {"kind": "png"})
        self.assertEqual(list(self.paths.media.iterdir()), [])
        self.assertEqual(self.library.playlist(self.cid), [])

    def test_corrupt_library_fails_closed(self):
        self.library.path.write_text('{"version":1,"collections":[]}')
        before = self.library.path.read_bytes()
        with self.assertRaises(ValueError):
            Library(self.paths)
        self.assertEqual(self.library.path.read_bytes(), before)

    def test_restored_duplicate_media_ids_rejected(self):
        item = self.add()
        data = read_json(self.library.path, 2_000_000)
        data["collections"][0]["items"].append(item)
        self.library.path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            Library(self.paths)

    def test_startup_reclaims_only_unreferenced_staged_media(self):
        item = self.add()
        orphan = self.paths.media / ("a" * 32)
        orphan.write_bytes(b"orphan")
        stream, temporary = self.library.temporary_upload()
        stream.close()
        Library(self.paths)
        self.assertFalse(orphan.exists())
        self.assertFalse(temporary.exists())
        self.assertTrue((self.paths.media / item["id"]).exists())


class PathTests(StorageCase):
    def test_filename_traversal_controls_and_absolute_paths(self):
        for name in ("../x.png", "/tmp/x", "a/b", "a\\b", "..", ".", "C:x", "hi\x00.png", "a\n.png", "a\u202eexe", "x"*161):
            with self.subTest(name=name), self.assertRaises(ValueError):
                display_name(name, 160)
        for value in ("../" + "a"*32, "/"+"a"*32, "A"*32, 3):
            with self.assertRaises(ValueError):
                identifier(value)

    def test_xdg_must_be_absolute_without_link_or_traversal(self):
        link = self.base / "linked"
        link.symlink_to(self.paths.data, target_is_directory=True)
        for value in ("relative", str(self.base) + "/../bad", str(link)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Paths({"HOME": str(self.base), "XDG_DATA_HOME": value})

    def test_all_xdg_paths_validated_before_any_directory_creation(self):
        target = self.base / "new-config"
        with self.assertRaises(ValueError):
            Paths({"HOME": str(self.base), "XDG_CONFIG_HOME": str(target), "XDG_DATA_HOME": "../unsafe"})
        self.assertFalse(target.exists())

    def test_symlink_media_and_metadata_rejected_without_mutation(self):
        item = self.add()
        media = self.paths.media / item["id"]
        media.unlink()
        outside = self.base / "outside"
        outside.write_bytes(b"safe")
        media.symlink_to(outside)
        with self.assertRaises((OSError, ValueError)):
            self.library.delete(self.cid, item["id"])
        self.assertEqual(outside.read_bytes(), b"safe")
        self.settings.path.symlink_to(outside)
        with self.assertRaises((OSError, ValueError)):
            self.settings.save(DEFAULTS)

    def test_fifo_hardlink_and_insecure_private_directory(self):
        path = self.paths.data / "fifo"
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            regular_open(path, 100)
        file = self.paths.data / "file"
        file.write_bytes(b"test")
        os.link(file, self.base / "hardlink")
        with self.assertRaises(ValueError):
            regular_open(file, 100)
        self.paths.media.chmod(0o755)
        with self.assertRaises(ValueError):
            self.library.open_item({"id": "a"*32})

    def test_single_instance_lock_and_release(self):
        lock = InstanceLock(self.paths.data)
        try:
            with self.assertRaises(BlockingIOError):
                InstanceLock(self.paths.data)
        finally:
            lock.close()
        InstanceLock(self.paths.data).close()

    def test_atomic_duplicate_key_rejection_and_sync_warning(self):
        path = self.paths.data / "test.json"
        path.write_text('{"key":1,"key":2}')
        with self.assertRaises(ValueError):
            read_json(path, 100)
        with patch("storage.sync_directory", side_effect=OSError("sync")):
            warning = atomic_json(path, {"ok": True}, 100)
        self.assertTrue(warning)
        self.assertEqual(read_json(path, 100), {"ok": True})
