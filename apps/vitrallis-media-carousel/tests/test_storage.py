import json
import os
from pathlib import Path
from unittest.mock import patch

from support import StorageCase, gif_bytes, webp_bytes
from library import Library, display_name, identifier
from settings import DEFAULTS, Settings, validate
from storage import InstanceLock, Paths, atomic_json, read_json, regular_open


class SettingsTests(StorageCase):
    def test_defaults_do_not_write_settings_on_read(self):
        self.assertEqual(self.settings.snapshot(), DEFAULTS)
        self.assertFalse(self.settings.path.exists())

    def test_convert_gifs_legacy_payload_and_type_validation(self):
        self.assertFalse(DEFAULTS["convert_gifs"])
        legacy = {"image_seconds": 3, "repeats": 2, "order": "shuffle", "loop": False}
        self.assertEqual(validate(legacy), dict(legacy, convert_gifs=False))
        for value in (1, 0, "yes", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(dict(DEFAULTS, convert_gifs=value))
        saved = dict(DEFAULTS, convert_gifs=True)
        self.settings.save(saved)
        self.assertEqual(Settings(self.paths.config).snapshot(), saved)

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
                            "order": ["random", None], "loop": [1, "yes"],
                            "convert_gifs": [1, 0, "yes", None]}.items():
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

    def test_upload_stores_animation_flag_from_probe(self):
        gif = self.add("clip.gif", gif_bytes(), "gif")
        webp = self.add("photo.webp", webp_bytes(), "webp")
        self.assertTrue(gif["animated"])
        self.assertFalse(webp["animated"])
        self.assertEqual(set(gif), {"id", "name", "kind", "size", "animated"})
        animated = self.add_animated("anim.webp", webp_bytes())
        self.assertTrue(animated["animated"])

    def add_animated(self, name, raw):
        stream, path = self.library.temporary_upload()
        with stream:
            stream.write(raw)
        return self.library.add_upload(self.cid, name, path, {"kind": "webp", "animated": True})

    def test_legacy_items_default_animation_and_reject_non_bool(self):
        rows = [{"id": "1" * 32, "name": "old.gif", "kind": "gif", "size": 10},
                {"id": "2" * 32, "name": "old.webp", "kind": "webp", "size": 10},
                {"id": "3" * 32, "name": "old.webm", "kind": "webm", "size": 10},
                {"id": "4" * 32, "name": "old.png", "kind": "png", "size": 10}]
        cid = "a" * 32
        def write():
            self.library.path.write_text(json.dumps(
                {"version": 1, "collections": [{"id": cid, "name": "Unsorted", "items": rows}]}))
        write()
        restored = Library(self.paths)
        self.assertEqual({item["name"]: item["animated"] for item in restored.playlist(cid)},
                         {"old.gif": True, "old.webp": False, "old.webm": True, "old.png": False})
        self.assertTrue(all(set(item) == {"id", "name", "kind", "size", "animated"}
                            for item in restored.playlist(cid)))
        rows[1]["animated"] = 1
        write()
        with self.assertRaises(ValueError):
            Library(self.paths)
        rows[1]["animated"] = "yes"
        write()
        with self.assertRaises(ValueError):
            Library(self.paths)

    def test_replace_upload_keeps_position_and_reclaims_old_blob(self):
        a, b, c = self.add("a.png"), self.add("b.png"), self.add("c.png")
        raw = webp_bytes()
        staged = self.paths.uploads / "convert-staged"
        staged.write_bytes(raw)
        replacement = self.library.replace_upload(self.cid, b["id"], "b.webp", staged,
                                                  {"kind": "webp", "animated": False})
        self.assertEqual([item["id"] for item in self.library.playlist(self.cid)],
                         [a["id"], replacement["id"], c["id"]])
        self.assertEqual(set(replacement), {"id", "name", "kind", "size", "animated"})
        self.assertEqual((replacement["name"], replacement["kind"]), ("b.webp", "webp"))
        self.assertEqual((replacement["size"], replacement["animated"]), (len(raw), False))
        self.assertFalse((self.paths.media / b["id"]).exists())
        self.assertTrue((self.paths.media / replacement["id"]).exists())
        self.assertFalse(staged.exists())
        restored = Library(self.paths)
        self.assertEqual([item["id"] for item in restored.playlist(self.cid)],
                         [a["id"], replacement["id"], c["id"]])

    def test_replace_upload_commit_failure_keeps_old_item_and_media(self):
        item = self.add()
        before = self.library.path.read_bytes()
        staged = self.paths.uploads / "convert-staged"
        staged.write_bytes(webp_bytes())
        with patch("library.atomic_json", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.library.replace_upload(self.cid, item["id"], "new.webp", staged, {"kind": "webp"})
        self.assertEqual(self.library.path.read_bytes(), before)
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertEqual([path.name for path in self.paths.media.iterdir()], [item["id"]])
        self.assertFalse(staged.exists())

    def test_replace_upload_rejects_unknown_item_and_foreign_staging(self):
        item = self.add()
        raw = webp_bytes()
        staged = self.paths.uploads / "upload-staged"
        staged.write_bytes(raw)
        with self.assertRaises(KeyError):
            self.library.replace_upload(self.cid, "f" * 32, "x.webp", staged, {"kind": "webp"})
        self.assertTrue(staged.exists())
        staged.unlink()
        foreign = self.base / "upload-foreign"
        foreign.write_bytes(raw)
        with self.assertRaises(ValueError):
            self.library.replace_upload(self.cid, item["id"], "x.webp", foreign, {"kind": "webp"})
        self.assertTrue(foreign.exists())

    def test_startup_reclaims_convert_staging(self):
        convert = self.paths.uploads / "convert-leftover"
        other = self.paths.uploads / "notes"
        convert.write_bytes(b"partial")
        other.write_bytes(b"keep")
        Library(self.paths)
        self.assertFalse(convert.exists())
        self.assertTrue(other.exists())

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

    def test_startup_survives_an_unsafe_unreferenced_entry(self):
        item = self.add()
        fifo = self.paths.media / ("b" * 32)
        os.mkfifo(fifo)
        library = Library(self.paths)
        self.assertTrue(fifo.exists())  # An entry that fails validation is never unlinked.
        self.assertIn("could not be cleaned up", library.warning)
        self.assertEqual(library.playlist(self.cid), [item])

    def test_startup_survives_a_dangling_unreferenced_symlink(self):
        link = self.paths.media / ("c" * 32)
        link.symlink_to(self.paths.media / "missing")
        library = Library(self.paths)
        self.assertTrue(link.is_symlink())
        self.assertIn("could not be cleaned up", library.warning)


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
