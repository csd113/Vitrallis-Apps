import io
import shutil
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from support import StorageCase, gif2webp_path, gif_bytes
from convert import ConversionError, Conversions, converted_name, converter_available
from library import Library
from media import Processes


def palette_gif(durations=(40, 80), loop=0, size=(32, 16)):
    frames = []
    for color in ((255, 0, 0), (0, 0, 255)):
        frame = Image.new("P", size, 0)
        frame.putpalette([color[0], color[1], color[2], 0, 0, 0] + [0, 0, 0] * 254)
        for x in range(4):
            for y in range(4):
                frame.putpixel((x, y), 1)
        frames.append(frame)
    stream = io.BytesIO()
    frames[0].save(stream, format="GIF", save_all=True, append_images=frames[1:],
                   duration=list(durations), loop=loop, disposal=2, transparency=1)
    return stream.getvalue()


def webp_frames(path):
    with Image.open(path) as result:
        durations = []
        for index in range(result.n_frames):
            result.seek(index)
            result.load()
            durations.append(result.info.get("duration"))
        return result.n_frames, result.info.get("loop"), durations


class ConversionTests(StorageCase):
    def setUp(self):
        super().setUp()
        self.processes = Processes()
        self.addCleanup(self.processes.close)
        self.conversions = Conversions(self.library, self.processes)
        self.addCleanup(self.conversions.close)

    def wait(self, timeout=20):
        with self.conversions.condition:
            self.assertTrue(self.conversions.condition.wait_for(
                lambda: self.conversions.snapshot()["status"] != "running", timeout=timeout))
        return self.conversions.snapshot()

    def test_snapshot_shape_and_name_conversion(self):
        idle = Conversions(self.library, self.processes)
        self.addCleanup(idle.close)
        state = idle.snapshot()
        self.assertEqual({key: state[key] for key in ("status", "message", "item", "replacement",
                                                      "name", "collection", "converter")},
                         {"status": "idle", "message": "", "item": None,
                          "replacement": None, "name": "", "collection": None,
                          "converter": ""})
        job = state["job"]
        self.assertEqual(job["status"], "idle")
        self.assertEqual((job["total"], job["completed"], job["failed"], job["skipped"]),
                         (0, 0, 0, 0))
        self.assertEqual(job["results"], [])
        self.assertEqual(converter_available(), shutil.which("gif2webp"))
        self.assertEqual(converted_name("holiday.GIF"), "holiday.webp")
        self.assertEqual(converted_name("clip"), "clip.webp")
        self.assertEqual(converted_name("photo.jpeg"), "photo.webp")
        self.assertEqual(len(converted_name("x" * 160 + ".gif")), 160)

    def test_start_rejects_unknown_media_and_unconvertible_kinds(self):
        video = self.add("clip.webm", b"video", "webm")
        with self.assertRaises((KeyError, ValueError)):
            self.conversions.start("f" * 32, video["id"])
        with self.assertRaises(KeyError):
            self.conversions.start(self.cid, "f" * 32)
        with self.assertRaises(ConversionError) as error:
            self.conversions.start(self.cid, video["id"])
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.conversions.snapshot()["status"], "idle")

    def test_static_images_convert_to_webp_and_keep_their_geometry(self):
        photo = self.add("photo.png")
        started = self.conversions.start(self.cid, photo["id"])
        self.assertEqual(started["status"], "running")
        self.assertEqual(started["job"]["total"], 1)
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["name"], "photo.webp")
        self.assertGreaterEqual(state["job"]["completed"], 1)
        with Image.open(self.paths.media / state["replacement"]) as result:
            self.assertEqual((result.format, result.size), ("WEBP", (64, 32)))
            self.assertFalse(result.is_animated)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_start_rejects_insufficient_free_space(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        with patch("convert.shutil.disk_usage") as usage:
            usage.return_value.free = 0
            with self.assertRaises(ConversionError) as error:
                self.conversions.start(self.cid, item["id"])
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.conversions.snapshot()["status"], "idle")

    def test_busy_conversion_is_rejected_with_409(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        started, release = threading.Event(), threading.Event()
        original = Conversions._convert_pillow
        def slow(instance, *args):
            started.set()
            release.wait(3)
            return original(instance, *args)
        self.addCleanup(release.set)
        with patch("convert.converter_available", return_value=None), \
                patch.object(Conversions, "_convert_pillow", slow):
            self.conversions.start(self.cid, item["id"])
            self.assertTrue(started.wait(3))
            with self.assertRaises(ConversionError) as error:
                self.conversions.start(self.cid, item["id"])
            self.assertEqual(error.exception.code, 409)
            release.set()
        self.assertEqual(self.wait()["status"], "ready")

    @unittest.skipUnless(gif2webp_path(), "Optional gif2webp unavailable")
    def test_real_gif2webp_conversion_preserves_animation(self):
        item = self.add("clip.gif", gif_bytes(frames=3, duration=(40, 80, 120), loop=0), "gif")
        started = self.conversions.start(self.cid, item["id"])
        self.assertEqual(started["status"], "running")
        self.assertEqual(started["converter"], "gif2webp")
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["message"], "Converted to WebP")
        self.assertEqual(state["item"], item["id"])
        self.assertEqual(state["name"], "clip.webp")
        self.assertEqual(state["collection"], self.cid)
        self.assertNotEqual(state["replacement"], item["id"])
        items = self.library.playlist(self.cid)
        self.assertEqual([row["id"] for row in items], [state["replacement"]])
        self.assertEqual(items[0]["kind"], "webp")
        self.assertTrue(items[0]["animated"])
        self.assertFalse((self.paths.media / item["id"]).exists())
        self.assertTrue((self.paths.media / state["replacement"]).exists())
        frames, loop, durations = webp_frames(self.paths.media / state["replacement"])
        self.assertEqual((frames, loop, durations), (3, 0, [40, 80, 120]))
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    @unittest.skipUnless(gif2webp_path(), "Optional gif2webp unavailable")
    def test_real_gif2webp_keeps_finite_loop_and_transparency(self):
        item = self.add("clip.gif", palette_gif(loop=2), "gif")
        self.conversions.start(self.cid, item["id"])
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        with Image.open(self.paths.media / state["replacement"]) as result:
            self.assertNotEqual(result.info.get("loop"), 0)
            for index in range(result.n_frames):
                result.seek(index)
                result.load()
                self.assertEqual(result.convert("RGBA").getpixel((1, 1))[3], 0)

    def test_pillow_fallback_preserves_frames_durations_transparency_and_infinite_loop(self):
        item = self.add("clip.gif", palette_gif(loop=0), "gif")
        with patch("convert.converter_available", return_value=None):
            started = self.conversions.start(self.cid, item["id"])
        self.assertEqual(started["converter"], "pillow")
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        items = self.library.playlist(self.cid)
        self.assertEqual([row["id"] for row in items], [state["replacement"]])
        frames, loop, durations = webp_frames(self.paths.media / state["replacement"])
        self.assertEqual((frames, loop, durations), (2, 0, [40, 80]))
        with Image.open(self.paths.media / state["replacement"]) as result:
            for index in range(result.n_frames):
                result.seek(index)
                result.load()
                self.assertEqual(result.convert("RGBA").getpixel((1, 1))[3], 0)
        self.assertFalse((self.paths.media / item["id"]).exists())
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    @unittest.skipUnless(gif2webp_path(), "Optional gif2webp unavailable")
    def test_zero_delay_frames_keep_the_standard_viewer_timing(self):
        item = self.add("clip.gif", gif_bytes(duration=(0, 80, 0)), "gif")
        self.conversions.start(self.cid, item["id"])
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        frames, loop, durations = webp_frames(self.paths.media / state["replacement"])
        self.assertEqual((frames, durations), (3, [100, 80, 100]))

    def test_pillow_fallback_uses_standard_delay_for_zero_delay_frames(self):
        item = self.add("clip.gif", gif_bytes(duration=(0, 80, 0)), "gif")
        with patch("convert.converter_available", return_value=None):
            self.conversions.start(self.cid, item["id"])
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        frames, loop, durations = webp_frames(self.paths.media / state["replacement"])
        self.assertEqual((frames, durations), (3, [100, 80, 100]))

    def test_pillow_fallback_keeps_finite_loop_non_zero(self):
        item = self.add("clip.gif", gif_bytes(loop=2), "gif")
        with patch("convert.converter_available", return_value=None):
            self.conversions.start(self.cid, item["id"])
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        frames, loop, durations = webp_frames(self.paths.media / state["replacement"])
        self.assertEqual(frames, 3)
        self.assertNotEqual(loop, 0)
        self.assertEqual(durations, [40, 80, 120])

    @unittest.skipUnless(gif2webp_path(), "Optional gif2webp unavailable")
    def test_conversion_keeps_playlist_position(self):
        before = self.add("before.png")
        item = self.add("clip.gif", gif_bytes(), "gif")
        after = self.add("after.png")
        self.conversions.start(self.cid, item["id"])
        state = self.wait()
        self.assertEqual(state["status"], "ready")
        self.assertEqual([row["id"] for row in self.library.playlist(self.cid)],
                         [before["id"], state["replacement"], after["id"]])

    def test_failed_conversion_keeps_source_and_reclaims_staging(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        before = (self.paths.media / item["id"]).read_bytes()
        for converter, method in (("gif2webp", "_convert_gif2webp"),
                                  (None, "_convert_pillow")):
            with self.subTest(converter=converter or "pillow"):
                with patch("convert.converter_available", return_value=converter), \
                        patch.object(Conversions, method,
                                     side_effect=ConversionError("converter exploded")):
                    self.conversions.start(self.cid, item["id"])
                    state = self.wait()
                self.assertEqual(state["status"], "failed")
                self.assertEqual(state["message"], "converter exploded")
                self.assertIsNone(state["replacement"])
                self.assertEqual(self.library.playlist(self.cid), [item])
                self.assertEqual((self.paths.media / item["id"]).read_bytes(), before)
                self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_publish_failure_keeps_source_and_reclaims_staging(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        before = (self.paths.media / item["id"]).read_bytes()
        with patch.object(Library, "replace_upload", side_effect=OSError("commit failed")):
            self.conversions.start(self.cid, item["id"])
            state = self.wait()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertEqual((self.paths.media / item["id"]).read_bytes(), before)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_corrupt_gif_fails_cleanly(self):
        stream, path = self.library.temporary_upload()
        with stream:
            stream.write(b"not really a gif")
        item = self.library.add_upload(self.cid, "broken.gif", path, {"kind": "gif"})
        self.conversions.start(self.cid, item["id"])
        state = self.wait()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertTrue((self.paths.media / item["id"]).exists())
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_fallback_pixel_budget_rejects_large_animation(self):
        item = self.add("clip.gif", gif_bytes(frames=3, size=(200, 200)), "gif")
        with patch("convert.converter_available", return_value=None), \
                patch("convert.FALLBACK_PIXEL_BUDGET", 100_000):
            self.conversions.start(self.cid, item["id"])
            state = self.wait()
        self.assertEqual(state["status"], "failed")
        self.assertIn("gif2webp", state["message"])
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_close_is_safe_before_and_after_jobs(self):
        idle = Conversions(self.library, self.processes)
        idle.close()
        idle.close()
        item = self.add("clip.gif", gif_bytes(), "gif")
        self.conversions.start(self.cid, item["id"])
        self.wait()
        self.conversions.close()
        self.conversions.close()
        self.assertEqual(self.conversions.snapshot()["status"], "ready")

    def test_close_cancels_a_running_job_and_reclaims_staging(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        entered = threading.Event()
        def waiting(instance, *args):
            entered.set()
            while not instance.cancel.wait(.05):
                pass
        conversions = Conversions(self.library, self.processes)
        with patch("convert.converter_available", return_value=None), \
                patch.object(Conversions, "_convert_pillow", waiting):
            conversions.start(self.cid, item["id"])
            self.assertTrue(entered.wait(3))
            conversions.close()
        self.assertEqual(conversions.snapshot()["status"], "idle")
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_close_reports_a_pillow_encode_that_ignores_cancellation(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        entered, release = threading.Event(), threading.Event()

        def slow(instance, stream, staged, details):
            entered.set()
            release.wait(10)  # like Pillow's C encoder: cannot observe cancellation
            return Conversions._convert_pillow(instance, stream, staged, details)

        conversions = Conversions(self.library, self.processes)
        with patch("convert.converter_available", return_value=None), \
                patch.object(Conversions, "_convert_pillow", slow):
            conversions.start(self.cid, item["id"])
            self.assertTrue(entered.wait(3))
            conversions.close()  # bounded: reports instead of blocking shutdown
            workers = [t for t in threading.enumerate()
                       if t.name.startswith("carousel-conversion")]
            self.assertTrue(workers)
            self.assertTrue(all(thread.daemon for thread in workers))
            release.set()
            for worker in workers:
                worker.join(timeout=10)
        # The abandoned encode never commits; its staging file is reclaimed.
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_verification_rejects_a_wrong_result(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        def static(instance, stream, staged, details):
            Image.new("RGB", (8, 8), "red").save(staged, format="WEBP")
        with patch("convert.converter_available", return_value=None), \
                patch.object(Conversions, "_convert_pillow", static):
            self.conversions.start(self.cid, item["id"])
            state = self.wait()
        self.assertEqual(state["status"], "failed")
        self.assertIn("frame count", state["message"])
        self.assertEqual(self.library.playlist(self.cid), [item])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])
