"""One-action bulk GIF/image to WebP conversion: reporting, safety and scoping."""
import io
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from support import StorageCase, animated_webp_bytes, gif2webp_path, gif_bytes, png_bytes
from convert import (ConversionError, Conversions, converted_name, needs_conversion)
from media import Processes


def gif(frames=2, duration=(40, 80), size=(24, 16)):
    """A tiny distinguishable animation with exactly `frames` frames."""
    palette = ("red", "blue", "green", "yellow", "purple", "orange")
    images = [Image.new("RGBA", size, palette[index % len(palette)]) for index in range(frames)]
    delays = [list(duration)[index % len(duration)] for index in range(frames)]
    stream = io.BytesIO()
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:],
                   duration=delays, loop=0, disposal=2)
    return stream.getvalue()


def jpeg(size=(32, 24), color=(10, 120, 200)):
    stream = io.BytesIO()
    image = Image.new("RGB", size, color)
    ImageDraw.Draw(image).rectangle((4, 4, 12, 12), fill=(255, 255, 255))
    image.save(stream, format="JPEG", quality=90)
    return stream.getvalue()


class BulkHarness(StorageCase):
    def setUp(self):
        super().setUp()
        self.processes = Processes()
        self.addCleanup(self.processes.close)
        self.conversions = Conversions(self.library, self.processes, workers=2)
        self.addCleanup(self.conversions.close)

    def put(self, name, raw, kind, animated=None, cid=None):
        stream, staged = self.library.temporary_upload()
        with stream:
            stream.write(raw)
        info = {"kind": kind}
        if animated is not None:
            info["animated"] = animated
        return self.library.add_upload(cid or self.cid, name, staged, info)

    def finish(self, timeout=90):
        with self.conversions.condition:
            self.assertTrue(self.conversions.condition.wait_for(
                lambda: self.conversions.snapshot()["job"]["status"]
                not in ("queued", "running"), timeout=timeout))
        return self.conversions.snapshot()

    def job(self, status="completed", timeout=90):
        state = self.finish(timeout)
        self.assertEqual(state["job"]["status"], status, state["job"]["message"])
        return state["job"]

    def convert(self, kinds, scope="collection", collection=None, replace=False):
        return self.conversions.start_bulk(scope, kinds, replace,
                                           collection if collection is not None else self.cid)

    def media(self, cid=None):
        return self.library.playlist(cid or self.cid)


class BulkConversionTests(BulkHarness):
    def test_one_action_converts_every_gif_and_image_in_the_collection(self):
        gifs = [self.put("one.gif", gif(), "gif"), self.put("two.gif", gif(), "gif")]
        images = [self.put("one.png", png_bytes(), "png"),
                  self.put("two.jpg", jpeg(), "jpeg")]
        started = self.convert(["gif", "image"])
        self.assertEqual(started["job"]["total"], 4)
        self.assertEqual(started["job"]["status"], "queued")
        job = self.job()
        self.assertEqual((job["completed"], job["failed"], job["skipped"]), (4, 0, 0))
        self.assertEqual(job["message"], "Converted 4")
        items = self.media()
        self.assertEqual([item["name"] for item in items],
                         ["one.webp", "two.webp", "one.webp", "two.webp"])
        self.assertTrue(all(item["kind"] == "webp" for item in items))
        self.assertEqual([item["id"] for item in items],
                         sorted({item["id"] for item in items}, key=[item["id"] for item in items].index))
        for original in gifs + images:
            self.assertFalse((self.paths.media / original["id"]).exists())
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_gif_only_and_image_only_actions_leave_the_other_kind_alone(self):
        animation = self.put("clip.gif", gif(), "gif")
        photo = self.put("photo.png", png_bytes(), "png")
        self.convert(["gif"])
        self.assertEqual(self.job()["completed"], 1)
        items = self.media()
        self.assertEqual(items[0]["kind"], "webp")
        self.assertTrue(items[0]["animated"])
        self.assertEqual(items[1]["id"], photo["id"])
        self.convert(["image"])
        self.assertEqual(self.job()["completed"], 1)
        items = self.media()
        self.assertEqual([item["kind"] for item in items], ["webp", "webp"])
        self.assertFalse(items[1]["animated"])
        self.assertEqual(self.media()[0]["id"], items[0]["id"])
        self.assertNotEqual(items[0]["id"], animation["id"])

    def test_existing_webp_is_reported_skipped_and_never_reconverted(self):
        webp = self.put("already.webp", animated_webp_bytes(size=(24, 16)), "webp", True)
        animation = self.put("clip.gif", gif(), "gif")
        before = (self.paths.media / webp["id"]).read_bytes()
        started = self.convert(["gif"])
        self.assertEqual(started["job"]["total"], 2)
        job = self.job()
        self.assertEqual((job["completed"], job["failed"], job["skipped"]), (1, 0, 1))
        self.assertIn("already WebP", job["message"])
        self.assertEqual((self.paths.media / webp["id"]).read_bytes(), before)
        self.assertEqual([row["item"] for row in job["results"] if row["status"] == "skipped"],
                         [webp["id"]])
        self.assertTrue((self.paths.media / animation["id"]).exists() is False)

    def test_replacement_reconverts_webp_when_the_user_asks_for_it(self):
        webp = self.put("already.webp", animated_webp_bytes(size=(24, 16)), "webp", True)
        self.convert(["gif"], replace=True)
        job = self.job()
        self.assertEqual((job["completed"], job["skipped"]), (1, 0))
        items = self.media()
        self.assertEqual(items[0]["kind"], "webp")
        self.assertNotEqual(items[0]["id"], webp["id"])
        self.assertFalse((self.paths.media / webp["id"]).exists())

    def test_all_collections_scope_keeps_every_folder_separate(self):
        other = self.library.create("Holiday")["id"]
        first = self.put("one.gif", gif(), "gif")
        second = self.put("two.png", png_bytes(), "png", cid=other)
        started = self.conversions.start_bulk("all", ["gif", "image"])
        self.assertEqual((started["job"]["scope"], started["job"]["total"]), ("all", 2))
        job = self.job()
        self.assertEqual(job["completed"], 2)
        self.assertEqual(job["scope_name"], "All collections")
        self.assertEqual([row["name"] for row in self.media()], ["one.webp"])
        self.assertEqual([row["kind"] for row in self.media()], ["webp"])
        self.assertEqual([row["name"] for row in self.media(other)], ["two.webp"])
        self.assertEqual([row["kind"] for row in self.media(other)], ["webp"])
        self.assertNotEqual(self.media()[0]["id"], first["id"])
        self.assertNotEqual(self.media(other)[0]["id"], second["id"])

    def test_webm_is_never_part_of_a_bulk_job(self):
        video = self.put("clip.webm", b"not a real video", "webm")
        with self.assertRaises(ConversionError):
            self.convert(["gif", "image"])
        self.assertEqual(self.conversions.snapshot()["job"]["status"], "idle")
        self.assertEqual(self.media(), [video])

    def test_malformed_media_fails_alone_and_the_batch_continues(self):
        broken = self.put("broken.gif", b"this is not a gif", "gif")
        truncated = self.put("cut.gif", gif()[:12], "gif")
        good = self.put("good.gif", gif(), "gif")
        photo = self.put("photo.png", png_bytes(), "png")
        self.convert(["gif", "image"])
        job = self.job()
        self.assertEqual((job["completed"], job["failed"]), (2, 2))
        self.assertEqual(job["message"], "Converted 2 · 2 failed")
        failures = {row["item"]: row["message"] for row in job["results"] if row["status"] == "failed"}
        self.assertEqual(set(failures), {broken["id"], truncated["id"]})
        self.assertTrue(all(message for message in failures.values()))
        items = self.media()
        by_name = {item["name"]: item for item in items}
        self.assertEqual(by_name["photo.webp"]["kind"], "webp")
        self.assertEqual(by_name["good.webp"]["kind"], "webp")
        self.assertEqual((by_name["broken.gif"]["kind"], by_name["cut.gif"]["kind"]),
                         ("gif", "gif"))
        for original in (broken, truncated):
            self.assertTrue((self.paths.media / original["id"]).exists())
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_animation_timing_transparency_and_dimensions_survive_a_batch(self):
        if not gif2webp_path():
            self.skipTest("Optional gif2webp unavailable")
        first = self.put("loop.gif", gif(frames=3, duration=(30, 70, 110)), "gif")
        second = self.put("still.png", png_bytes(size=(48, 32)), "png")
        self.convert(["gif", "image"])
        self.assertEqual(self.job()["completed"], 2)
        items = self.media()
        with Image.open(self.paths.media / items[0]["id"]) as result:
            self.assertTrue(result.is_animated)
            self.assertEqual((result.size, result.n_frames), ((24, 16), 3))
            durations = []
            for index in range(result.n_frames):
                result.seek(index)
                result.load()
                durations.append(result.info.get("duration"))
            self.assertEqual(durations, [30, 70, 110])
        with Image.open(self.paths.media / items[1]["id"]) as result:
            self.assertEqual((result.format, result.size), ("WEBP", (48, 32)))
            self.assertFalse(result.is_animated)

    def test_filenames_with_spaces_unicode_and_case_survive(self):
        names = ["Holiday clip 2024.gif", "Café – soirée.gif", "Ünïcode image.PNG", "naïve.jpeg"]
        for index, name in enumerate(names):
            kind = name.rsplit(".", 1)[1].casefold()
            kind = {"jpg": "jpeg"}.get(kind, kind)
            self.put(name, gif() if kind == "gif" else jpeg(), kind)
        self.convert(["gif", "image"])
        self.assertEqual(self.job()["completed"], 4)
        stored = [item["name"] for item in self.media()]
        self.assertEqual(stored, [converted_name(name) for name in names])
        for item in self.media():
            self.assertEqual(item["kind"], "webp")
            self.assertTrue((self.paths.media / item["id"]).exists())

    def test_progress_reports_the_current_item_and_final_totals(self):
        for index in range(4):
            self.put("clip-%d.gif" % index, gif(), "gif")
        started = self.convert(["gif"])
        self.assertEqual((started["job"]["total"], started["job"]["completed"]), (4, 0))
        self.assertTrue(started["name"].endswith(".webp"))
        self.assertEqual(started["collection"], self.cid)
        self.assertEqual(started["converter"], "gif2webp" if gif2webp_path() else "pillow")
        job = self.job()
        self.assertEqual(job["completed"], 4)
        self.assertEqual(job["current"].endswith(".gif"), True)
        self.assertEqual(len(job["results"]), 4)
        self.assertEqual([row["status"] for row in job["results"]], ["converted"] * 4)
        self.assertGreater(job["finished"], job["started"])

    def test_cancelling_a_batch_leaves_every_source_intact(self):
        items = [self.put("clip-%d.gif" % index, gif(frames=3), "gif") for index in range(6)]
        before = {item["id"]: (self.paths.media / item["id"]).read_bytes() for item in items}
        entered = threading.Event()
        original = Conversions._convert_one
        def slow(instance, cancel, cid, item, name):
            entered.set()
            time.sleep(.05)
            return original(instance, cancel, cid, item, name)
        self.conversions.workers = 1
        with patch.object(Conversions, "_convert_one", slow):
            self.convert(["gif"])
            self.assertTrue(entered.wait(5))
            self.conversions.request_cancel()
            state = self.finish()
        self.assertEqual(state["job"]["status"], "cancelled")
        self.assertEqual(state["job"]["message"], "Conversion cancelled")
        for item in items:
            if (self.paths.media / item["id"]).exists():
                self.assertEqual((self.paths.media / item["id"]).read_bytes(), before[item["id"]])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_a_second_batch_is_rejected_while_one_runs(self):
        for index in range(3):
            self.put("clip-%d.gif" % index, gif(), "gif")
        release = threading.Event()
        original = Conversions._convert_one
        def slow(instance, cancel, cid, item, name):
            release.wait(3)
            return original(instance, cancel, cid, item, name)
        with patch.object(Conversions, "_convert_one", slow):
            self.convert(["gif"])
            with self.assertRaises(ConversionError) as error:
                self.convert(["gif"])
            self.assertEqual(error.exception.code, 409)
            release.set()
        self.assertEqual(self.job()["completed"], 3)

    def test_converter_failure_keeps_every_source_byte_for_byte(self):
        items = [self.put("clip-%d.gif" % index, gif(), "gif") for index in range(3)]
        before = {item["id"]: (self.paths.media / item["id"]).read_bytes() for item in items}
        with patch.object(Conversions, "_verify", side_effect=ConversionError("verification exploded")):
            self.convert(["gif"])
            job = self.job(status="failed")
        self.assertEqual((job["completed"], job["failed"]), (0, 3))
        self.assertEqual(job["message"], "Conversion failed for every item")
        self.assertEqual(self.media(), items)
        for item in items:
            self.assertEqual((self.paths.media / item["id"]).read_bytes(), before[item["id"]])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_pillow_fallback_covers_a_mixed_batch_without_gif2webp(self):
        animation = self.put("clip.gif", gif(frames=3, duration=(40, 80, 120)), "gif")
        photo = self.put("photo.png", png_bytes(), "png")
        with patch("convert.converter_available", return_value=None):
            self.convert(["gif", "image"])
            job = self.job()
        self.assertEqual(job["completed"], 2)
        self.assertEqual(job["converter"], "pillow")
        items = self.media()
        with Image.open(self.paths.media / items[0]["id"]) as result:
            self.assertEqual(result.n_frames, 3)
            durations = []
            for index in range(result.n_frames):
                result.seek(index)
                result.load()
                durations.append(result.info.get("duration"))
            self.assertEqual(durations, [40, 80, 120])
        with Image.open(self.paths.media / items[1]["id"]) as result:
            self.assertEqual(result.size, (64, 32))
        self.assertFalse((self.paths.media / animation["id"]).exists())
        self.assertFalse((self.paths.media / photo["id"]).exists())

    def test_a_batch_with_nothing_to_do_is_refused_with_a_clear_message(self):
        self.put("already.webp", animated_webp_bytes(), "webp", True)
        with self.assertRaises(ConversionError) as error:
            self.convert(["image"])
        self.assertIn("Nothing to convert", str(error.exception))
        self.assertEqual(self.conversions.snapshot()["job"]["status"], "idle")

    def test_needs_conversion_marks_only_real_targets(self):
        self.assertTrue(needs_conversion({"kind": "gif"}))
        self.assertTrue(needs_conversion({"kind": "png"}))
        self.assertTrue(needs_conversion({"kind": "jpeg"}))
        self.assertFalse(needs_conversion({"kind": "webp", "animated": True}))
        self.assertFalse(needs_conversion({"kind": "webm"}))
