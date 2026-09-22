import io
from pathlib import Path
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from support import StorageCase, animated_webp_bytes, gif_bytes, png_bytes, webp_bytes
from media import (MediaError, Processes, cached_probe, forget_probe, frame_rate,
                   inspect_stream, playback_fps, probe, remember_probe, video_command)
from player import LOOKAHEAD, Decoder, PlaybackClock, Playlist, gif_seconds, video_backend
from settings import DEFAULTS


def make_webm(path):
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x32:rate=10:duration=0.3", "-c:v", "libvpx", "-threads", "1",
                    "-pix_fmt", "yuv420p", "-an", "-y", str(path)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)


class SequencingTests(unittest.TestCase):
    def playlist(self, **changes):
        return Playlist([{"id": str(i)} for i in range(5)], dict(DEFAULTS, **changes), random.Random(19))

    def test_ordered_sequence_return_to_menu(self):
        playlist = self.playlist(loop=False)
        self.assertEqual([playlist.next()["id"] for _ in range(5)], list("01234"))
        self.assertIsNone(playlist.next())

    def test_ordered_loop_and_previous(self):
        playlist = self.playlist()
        self.assertEqual([playlist.next()["id"] for _ in range(7)], list("0123401"))
        self.assertEqual(playlist.previous()["id"], "0")
        self.assertEqual(playlist.previous()["id"], "0")

    def test_shuffle_each_cycle_and_no_boundary_repeat(self):
        playlist = self.playlist(order="shuffle")
        cycles = [[playlist.next()["id"] for _ in range(5)] for _ in range(30)]
        for cycle in cycles:
            self.assertEqual(set(cycle), set("01234"))
        for first, second in zip(cycles, cycles[1:]):
            self.assertNotEqual(first[-1], second[0])
        self.assertGreater(len({tuple(cycle) for cycle in cycles}), 10)

    def test_shuffle_return_after_exactly_one_cycle(self):
        playlist = self.playlist(order="shuffle", loop=False)
        self.assertEqual(len({playlist.next()["id"] for _ in range(5)}), 5)
        self.assertIsNone(playlist.next())

    def test_skip_bad_items_and_finish_when_all_bad(self):
        playlist = self.playlist()
        playlist.next()
        self.assertEqual(playlist.failed()["id"], "1")
        for _ in range(3):
            self.assertIsNotNone(playlist.failed())
        self.assertIsNone(playlist.failed())

    def test_failed_item_excluded_from_next_cycles(self):
        playlist = self.playlist()
        playlist.next()
        playlist.failed()
        self.assertNotIn("0", [playlist.next()["id"] for _ in range(16)])

    def test_static_timer_and_pause_remaining_duration(self):
        now = [100.0]
        clock = PlaybackClock(lambda: now[0])
        clock.arm(5)
        now[0] = 102
        self.assertFalse(clock.ready())
        clock.toggle()
        now[0] = 120
        self.assertFalse(clock.ready())
        clock.toggle()
        now[0] = 122.9
        self.assertFalse(clock.ready())
        now[0] = 123
        self.assertTrue(clock.ready())

    def test_animation_deadlines_do_not_accumulate_upload_time(self):
        now = [0.0]
        clock = PlaybackClock(lambda: now[0])
        clock.arm(.04, continuous=True)
        now[0] = .065  # expensive presentation and scheduler delay
        clock.arm(.08, continuous=True)
        self.assertAlmostEqual(clock.deadline, .12)
        now[0] = .115
        self.assertLessEqual(clock.delay_ms(), 6)
        clock.toggle()
        now[0] = 50
        clock.toggle()
        self.assertAlmostEqual(clock.deadline, 50.005)
        now[0] = 51
        self.assertTrue(clock.ready())
        self.assertEqual(clock.delay_ms(), 1)

    def test_pause_while_preparing_does_not_start_the_animation_clock(self):
        now = [0.0]
        clock = PlaybackClock(lambda: now[0])
        clock.toggle()
        now[0] = 10.0
        clock.toggle()
        self.assertIsNone(clock.deadline)
        now[0] = 20.0
        clock.arm(.04, continuous=True)
        self.assertAlmostEqual(clock.deadline, 20.04)
        self.assertFalse(clock.ready())

    def test_gif_timing_bounds(self):
        self.assertEqual(gif_seconds(80), .08)
        self.assertEqual(gif_seconds(1), .02)
        self.assertEqual(gif_seconds(20000), 10)
        self.assertEqual(gif_seconds(float("nan")), .1)
        self.assertEqual(gif_seconds(None), .1)


class DecodeTests(StorageCase):
    def decoder(self):
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        return decoder

    def animated(self, name, raw, kind):
        stream, path = self.library.temporary_upload()
        with stream:
            stream.write(raw)
        return self.library.add_upload(self.cid, name, path, {"kind": kind, "animated": True})

    def events(self, decoder, timeout=10):
        result, deadline = [], time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = decoder.events.get(timeout=max(.01, deadline - time.monotonic()))
            result.append(event)
            if event[1] in ("done", "error"):
                return result
        self.fail("Decoder did not complete")

    def test_still_image_scaled_without_distortion_and_timed(self):
        item = self.add(content=png_bytes(size=(800, 400)))
        decoder = self.decoder()
        decoder.request(item, (480, 272), DEFAULTS)
        events = self.events(decoder)
        self.assertEqual([event[1] for event in events], ["frame", "done"])
        self.assertEqual(events[0][2].size, (480, 240))
        self.assertEqual(events[0][3], 5)

    def test_gif_exact_complete_replays_and_frame_timing(self):
        item = self.add("animation.gif", gif_bytes(), "gif")
        decoder = self.decoder()
        decoder.request(item, (480, 272), dict(DEFAULTS, repeats=3))
        events = self.events(decoder)
        frames = [event for event in events if event[1] == "frame"]
        self.assertEqual(len(frames), 9)
        self.assertEqual([event[3] for event in frames], [.04, .08, .12] * 3)
        self.assertEqual({frame[2].mode for frame in frames}, {"RGBA"})
        self.assertNotEqual(frames[0][2].image().getpixel((0, 0)),
                            frames[1][2].image().getpixel((0, 0)))

    def test_gpu_gif_keeps_native_size_and_reuses_bounded_composited_frames(self):
        item = self.add("animation.gif", gif_bytes(), "gif")
        decoder = self.decoder()
        decoder.request(item, (24, 12), dict(DEFAULTS, repeats=2), gpu=True)
        frames = [event for event in self.events(decoder) if event[1] == "frame"]
        self.assertEqual(len(frames), 6)
        self.assertTrue(all(event[2].size == (48, 24) for event in frames))
        self.assertIs(frames[0][2], frames[3][2])
        self.assertEqual([event[3] for event in frames], [.04, .08, .12] * 2)

    def test_gif_over_cache_budget_streams_repeats_without_retaining_frames(self):
        item = self.add("animation.gif", gif_bytes(), "gif")
        decoder = self.decoder()
        with patch("player.MAX_ANIMATION_BYTES", 0):
            decoder.request(item, (24, 12), dict(DEFAULTS, repeats=2), gpu=True)
            frames = [event for event in self.events(decoder) if event[1] == "frame"]
        self.assertEqual(len(frames), 6)
        self.assertIsNot(frames[0][2], frames[3][2])
        self.assertEqual(frames[0][2].tobytes(), frames[3][2].tobytes())

    def test_static_webp_uses_the_still_path(self):
        item = self.add("photo.webp", webp_bytes(), "webp")
        decoder = self.decoder()
        decoder.request(item, (480, 272), DEFAULTS)
        events = self.events(decoder)
        self.assertEqual([event[1] for event in events], ["frame", "done"])
        self.assertEqual(events[0][2].size, (64, 32))
        self.assertEqual(events[0][3], DEFAULTS["image_seconds"])

    def test_animated_webp_replays_every_frame_with_gif_timing(self):
        item = self.animated("animation.webp", animated_webp_bytes(), "webp")
        decoder = self.decoder()
        decoder.request(item, (480, 272), dict(DEFAULTS, repeats=3))
        frames = [event for event in self.events(decoder) if event[1] == "frame"]
        self.assertEqual(len(frames), 9)
        self.assertEqual([event[3] for event in frames], [.04, .08, .12] * 3)
        self.assertEqual({frame[2].mode for frame in frames}, {"RGBA"})
        self.assertNotEqual(frames[0][2].image().getpixel((0, 0)),
                            frames[1][2].image().getpixel((0, 0)))

    def test_webp_and_gif_frames_share_the_same_durations(self):
        gif = self.add("animation.gif", gif_bytes(), "gif")
        webp = self.animated("animation.webp", animated_webp_bytes(), "webp")
        decoder = self.decoder()
        sequences = []
        for item in (gif, webp):
            decoder.request(item, (480, 272), dict(DEFAULTS, repeats=1))
            frames = [event for event in self.events(decoder) if event[1] == "frame"]
            sequences.append([event[3] for event in frames])
        self.assertEqual(sequences, [[.04, .08, .12], [.04, .08, .12]])

    def test_gpu_animated_webp_reuses_prepared_frames_across_repeats(self):
        item = self.animated("animation.webp", animated_webp_bytes(), "webp")
        decoder = self.decoder()
        decoder.request(item, (24, 12), dict(DEFAULTS, repeats=2), gpu=True)
        frames = [event for event in self.events(decoder) if event[1] == "frame"]
        self.assertEqual(len(frames), 6)
        self.assertTrue(all(event[2].size == (48, 24) for event in frames))
        self.assertIs(frames[0][2], frames[3][2])
        self.assertEqual([event[3] for event in frames], [.04, .08, .12] * 2)

    def test_webp_over_cache_budget_streams_repeats_without_retaining_frames(self):
        item = self.animated("animation.webp", animated_webp_bytes(), "webp")
        decoder = self.decoder()
        with patch("player.MAX_ANIMATION_BYTES", 0):
            decoder.request(item, (24, 12), dict(DEFAULTS, repeats=2), gpu=True)
            frames = [event for event in self.events(decoder) if event[1] == "frame"]
        self.assertEqual(len(frames), 6)
        self.assertIsNot(frames[0][2], frames[3][2])
        self.assertEqual(frames[0][2].tobytes(), frames[3][2].tobytes())

    def test_truncated_animated_webp_reports_an_error_without_hanging(self):
        raw = animated_webp_bytes()
        item = self.animated("broken.webp", raw[:len(raw) // 2], "webp")
        decoder = self.decoder()
        decoder.request(item, (480, 272), dict(DEFAULTS, repeats=2))
        event = self.events(decoder)[-1]
        self.assertEqual(event[1], "error")
        decoder.request(self.add(), (480, 272), DEFAULTS)
        self.assertEqual(self.events(decoder)[-1][1], "done")

    def test_repeated_still_requests_reuse_decoded_image_and_stay_bounded(self):
        first = self.add("one.png", png_bytes(size=(64, 32)))
        second = self.add("two.png", png_bytes(size=(80, 40)))
        decoder = self.decoder()
        decodes, opens = [], []
        original_image, original_open = Image.open, self.library.open_item
        def decoding(*args, **kwargs):
            decodes.append(args)
            return original_image(*args, **kwargs)
        def opening(item):
            opens.append(item["id"])
            return original_open(item)
        with patch("player.Image.open", side_effect=decoding), \
                patch.object(self.library, "open_item", side_effect=opening):
            for _ in range(2):
                decoder.request(first, (64, 32), DEFAULTS)
                self.assertEqual(self.events(decoder)[-1][1], "done")
            self.assertEqual(opens, [first["id"]])
            self.assertEqual(len(decodes), 1)
            with patch("player.MAX_STILL_BYTES", 64 * 32 * 4 + 80 * 40 * 4 - 1):
                decoder.request(second, (80, 40), DEFAULTS)
                self.assertEqual(self.events(decoder)[-1][1], "done")
                self.assertEqual(len(decodes), 2)
                self.assertEqual(len(decoder.still_cache), 1)
                self.assertEqual(next(iter(decoder.still_cache))[0], second["id"])
                self.assertEqual(decoder.still_bytes, 80 * 40 * 4)
                self.assertLessEqual(decoder.still_bytes, 64 * 32 * 4 + 80 * 40 * 4 - 1)
        decoder.stop()
        self.assertEqual(decoder.still_cache, {})
        self.assertEqual(decoder.still_bytes, 0)

    def test_resized_still_is_not_served_from_cache(self):
        item = self.add("photo.png", png_bytes())
        decoder = self.decoder()
        decoder.request(item, (64, 32), DEFAULTS)
        self.assertEqual(self.events(decoder)[-1][1], "done")
        self.assertTrue(decoder.still_cache)
        with (self.paths.media / item["id"]).open("ab") as stream:
            stream.write(b"changed")
        decoder.request(item, (64, 32), DEFAULTS)
        event = self.events(decoder)[-1]
        self.assertEqual(event[1], "error")
        self.assertIn("size", event[2])

    def test_stop_clears_animation_and_still_caches(self):
        clip = self.add("animation.gif", gif_bytes(), "gif")
        photo = self.add("photo.png", png_bytes())
        decoder = self.decoder()
        decoder.request(photo, (64, 32), DEFAULTS)
        self.assertEqual(self.events(decoder)[-1][1], "done")
        decoder.request(clip, (48, 24), dict(DEFAULTS, repeats=1), upcoming=[clip])
        self.assertEqual(self.events(decoder)[-1][1], "done")
        self.assertTrue(decoder.still_cache)
        self.assertTrue(decoder.animation_cache.entries)
        decoder.stop()
        self.assertEqual(decoder.still_cache, {})
        self.assertEqual(decoder.animation_cache.entries, {})

    def test_missing_and_corrupt_files_emit_error_then_recover(self):
        item = self.add(content=b"corrupt")
        decoder = self.decoder()
        decoder.request(item, (480, 272), DEFAULTS)
        self.assertEqual(self.events(decoder)[-1][1], "error")
        (self.paths.media / item["id"]).unlink()
        decoder.request(item, (480, 272), DEFAULTS)
        self.assertEqual(self.events(decoder)[-1][1], "error")
        decoder.request(self.add(), (480, 272), DEFAULTS)
        self.assertEqual(self.events(decoder)[-1][1], "done")

    def test_bounded_queue_rapid_skip_and_stop(self):
        decoder = self.decoder()
        item = self.add("animation.gif", gif_bytes(), "gif")
        for _ in range(40):
            latest = decoder.request(item, (480, 272), dict(DEFAULTS, repeats=100))
        time.sleep(.1)
        self.assertLessEqual(decoder.events.qsize(), LOOKAHEAD + 2)
        # Cold ARMv7 decoders can take several seconds to supply their first frame.
        # This wait measures availability, not shutdown (still capped at 3 seconds).
        self.assertEqual(decoder.events.get(timeout=10)[0], latest)
        decoder.close()
        self.assertFalse(decoder.thread.is_alive())

    def test_missing_ffmpeg_does_not_break_images(self):
        decoder = self.decoder()
        video = self.add("clip.webm", b"video", "webm")
        with patch("media.shutil.which", return_value=None):
            decoder.request(video, (480, 272), DEFAULTS)
            error = self.events(decoder)[-1]
            self.assertEqual(error[1], "error")
            self.assertIn("ffmpeg", error[2])
            decoder.request(self.add(), (480, 272), DEFAULTS)
            self.assertEqual(self.events(decoder)[-1][1], "done")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Optional system FFmpeg unavailable")
    def test_real_webm_probe_frames_repeats_and_shutdown(self):
        source = self.base / "sample.webm"
        make_webm(source)
        processes = Processes()
        self.addCleanup(processes.close)
        stream, staged = self.library.temporary_upload()
        with stream:
            stream.write(source.read_bytes())
        info = probe(staged, processes)
        self.assertEqual(info["kind"], "webm")
        item = self.library.add_upload(self.cid, "sample.webm", staged, info)
        decoder = self.decoder()
        decoder.request(item, (96, 64), dict(DEFAULTS, repeats=3))
        frames = [event for event in self.events(decoder) if event[1] == "frame"]
        # Three source frames at 10 fps repeated three times, paced at the source
        # rate rather than a fixed decoder guess.
        self.assertEqual(len(frames), 9)
        self.assertTrue(all(frame[2].size == (96, 64) for frame in frames))
        self.assertEqual({frame[2].mode for frame in frames}, {"RGB"})
        self.assertEqual([round(frame[3], 4) for frame in frames], [0.1] * 9)
        self.assertNotEqual(frames[0][2].tobytes(), frames[1][2].tobytes())
        decoder.request(item, (480, 272), dict(DEFAULTS, repeats=100))
        decoder.events.get(timeout=10)
        active = list(decoder.processes.active)
        decoder.close()
        self.assertFalse(decoder.thread.is_alive())
        self.assertTrue(all(process.poll() is not None for process in active))

    def test_video_command_is_muted_local_and_scaled(self):
        with patch("media.shutil.which", return_value="/usr/bin/ffmpeg"):
            command = video_command(8, (480, 272))
        self.assertIn("-an", command)
        self.assertIn("file,pipe", command)
        self.assertIn("/dev/fd/8", command)
        self.assertTrue(any("scale=480:272" in part for part in command))
        self.assertTrue(any("fps=25" in part for part in command))

    def test_video_command_uses_the_source_rate_and_verified_hardware(self):
        with patch("media.shutil.which", return_value="/usr/bin/ffmpeg"):
            command = video_command(8, (480, 272), fps=12.5, hwaccel="videotoolbox", loop=True)
        self.assertIn("-hwaccel", command)
        self.assertIn("videotoolbox", command)
        self.assertIn("-stream_loop", command)
        self.assertTrue(any("fps=12.5" in part for part in command))
        self.assertLess(command.index("-hwaccel"), command.index("-i"),
                        "hardware selection is an input option")
        # The 20 fps guess and its 33% timing error are gone.
        self.assertFalse(any("fps=20" in part for part in command))

    def test_frame_rate_parsing_clamps_to_a_presentable_rate(self):
        self.assertEqual(frame_rate("25/1"), 25.0)
        self.assertEqual(frame_rate("30000/1001"), 30000 / 1001)
        self.assertIsNone(frame_rate("0/0"))
        self.assertIsNone(frame_rate(None))
        self.assertIsNone(frame_rate("nonsense"))
        self.assertEqual(playback_fps("60/1"), 30.0)
        self.assertEqual(playback_fps("10/1"), 10.0)
        self.assertEqual(playback_fps(None), 25.0)
        self.assertEqual(playback_fps("0/1"), 25.0)

    def test_hardware_acceleration_is_only_claimed_when_verified(self):
        backend = video_backend("vp9")
        self.assertIn("verified", backend)
        self.assertIn("reason", backend)
        if backend["verified"]:
            self.assertIsNotNone(backend["method"])
            self.assertIn(backend["method"], backend["name"] + backend["reason"])
        else:
            # A codec with no verified hardware path must fall back, never pretend.
            self.assertIsNone(backend["method"])
            self.assertEqual(backend["name"], "software")
        self.assertIsNone(video_backend(None)["method"])
        with patch("multimedia.executable_key", return_value=None):
            self.assertIsNone(video_backend("vp9")["method"])
        # A codec with no committed fixture is never claimed as accelerated.
        self.assertIsNone(video_backend("av1")["method"])

    def test_probe_cache_answers_playback_metadata_without_re_probing(self):
        item = self.add("clip.mp4", b"video", "webm")
        remember_probe((item["id"], item["size"]), {"kind": "webm", "duration": 1.5, "fps": 12})
        cached = cached_probe((item["id"], item["size"]))
        self.assertEqual(cached["fps"], 12)
        remember_probe(("x", 1), {"kind": "webm"})
        self.assertEqual(len(cached_probe(("x", 1))), 1)
        forget_probe(("x", 1))
        self.assertIsNone(cached_probe(("x", 1)))


class InspectionTests(unittest.TestCase):
    def test_actual_format_not_extension(self):
        self.assertEqual(inspect_stream(io.BytesIO(png_bytes()))["kind"], "png")
        self.assertEqual(inspect_stream(io.BytesIO(gif_bytes()))["frames"], 3)

    def test_animation_flags_for_gif_and_webp(self):
        gif = inspect_stream(io.BytesIO(gif_bytes()))
        self.assertEqual((gif["kind"], gif["frames"], gif["animated"]), ("gif", 3, True))
        webp = inspect_stream(io.BytesIO(animated_webp_bytes()))
        self.assertEqual((webp["kind"], webp["frames"], webp["animated"]), ("webp", 3, True))
        static = inspect_stream(io.BytesIO(webp_bytes()))
        self.assertEqual((static["kind"], static["frames"], static["animated"]), ("webp", 1, False))
        still = inspect_stream(io.BytesIO(gif_bytes(frames=1)))
        self.assertEqual((still["kind"], still["frames"], still["animated"]), ("gif", 1, False))

    def test_animated_png_has_no_playback_path_and_is_rejected(self):
        stream = io.BytesIO()
        frames = [Image.new("RGBA", (16, 16), color) for color in ("red", "blue")]
        frames[0].save(stream, format="PNG", save_all=True, append_images=frames[1:],
                       duration=[40, 80])
        self.assertTrue(Image.open(io.BytesIO(stream.getvalue())).is_animated)
        with self.assertRaises(MediaError):
            inspect_stream(io.BytesIO(stream.getvalue()))

    def test_unsupported_corrupt_and_oversized_dimensions(self):
        for raw in (b"<script>alert(1)</script>", png_bytes()[:30], b"\x1aE\xdf\xa3\x81\x00"):
            with self.assertRaises((OSError, ValueError, EOFError)):
                inspect_stream(io.BytesIO(raw))
        with self.assertRaises(MediaError):
            inspect_stream(io.BytesIO(png_bytes(size=(3000, 3000))))
        with self.assertRaises(MediaError):
            inspect_stream(io.BytesIO(gif_bytes(size=(1200, 1000))))


class ProcessTests(unittest.TestCase):
    def test_concurrent_finish_and_shutdown_reap_each_owned_child(self):
        for _ in range(5):
            processes = Processes()
            child = processes.start([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                                    stdout=subprocess.DEVNULL)
            gate = threading.Barrier(3)
            failures = []
            def finish(close):
                gate.wait()
                try:
                    processes.close() if close else processes.finish(child)
                except Exception as error:
                    failures.append(error)
            workers = [threading.Thread(target=finish, args=(close,)) for close in (False, True)]
            for worker in workers:
                worker.start()
            gate.wait()
            for worker in workers:
                worker.join(timeout=3)
            self.assertFalse(failures)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertIsNotNone(child.poll())
            self.assertFalse(processes.active)
