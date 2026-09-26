"""Bounded, timestamped FFmpeg video decoding with verified backend selection."""
import queue
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from support import StorageCase
from media import MediaError, Processes, probe, video_command
from player import LOOKAHEAD, Decoder, VideoStream, video_backend
from settings import DEFAULTS


def make_webm(path, size="64x32", rate=10, duration=0.3, codec="libvpx"):
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=%s:rate=%d:duration=%s" % (size, rate, duration),
                    "-c:v", codec, "-threads", "1", "-pix_fmt", "yuv420p", "-an",
                    "-y", str(path)], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=30)


def ffmpeg_ready():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class VideoStreamTests(StorageCase):
    def stream(self, raw, size=(64, 32), **kwargs):
        source = self.base / "clip.webm"
        source.write_bytes(raw)
        stream = source.open("rb")
        self.addCleanup(stream.close)
        return stream

    def collect(self, video, limit=1000):
        frames = []
        for raw in video.frames():
            frames.append(raw)
            if len(frames) >= limit:
                break
        return frames

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_one_process_serves_every_repeat_with_source_timestamps(self):
        source = self.base / "clip.webm"
        make_webm(source, rate=10, duration=0.3)
        processes = Processes()
        self.addCleanup(processes.close)
        stream = source.open("rb")
        self.addCleanup(stream.close)
        video = VideoStream(processes, stream, (64, 32), 10, repeats=3, hwaccel=None, loop=True)
        try:
            frames = self.collect(video, limit=9)
        finally:
            video.close()
        self.assertEqual(len(frames), 9)
        self.assertTrue(all(len(frame) == 64 * 32 * 3 for frame in frames))
        self.assertAlmostEqual(video.seconds, 0.1)
        self.assertGreaterEqual(video.produced, 9)
        self.assertEqual(processes.active, set())

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_is_opaque_rgb_and_shares_no_decoded_frame(self):
        source = self.base / "clip.webm"
        make_webm(source, duration=0.2)
        processes = Processes()
        self.addCleanup(processes.close)
        stream = source.open("rb")
        self.addCleanup(stream.close)
        video = VideoStream(processes, stream, (32, 32), 10, repeats=1)
        try:
            frames = self.collect(video, limit=2)
        finally:
            video.close()
        self.assertEqual(len(frames), 2)
        self.assertIsNot(frames[0], frames[1])
        self.assertIsInstance(frames[0], bytes)

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_the_decoded_queue_is_bounded(self):
        source = self.base / "clip.webm"
        make_webm(source, rate=30, duration=2.0)
        processes = Processes()
        self.addCleanup(processes.close)
        stream = source.open("rb")
        self.addCleanup(stream.close)
        video = VideoStream(processes, stream, (64, 32), 30, repeats=1)
        self.assertLessEqual(video.depth, 24)
        self.assertGreaterEqual(video.depth, 2)
        # The reader must not run away: the pipe stays nearly idle while the
        # consumer ignores the queue.
        video.start()
        try:
            time.sleep(0.5)
            self.assertLessEqual(video.queue.qsize(), 24)
        finally:
            video.close()

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_cancel_interrupts_a_full_queue_and_reaps_the_process(self):
        source = self.base / "clip.webm"
        make_webm(source, rate=30, duration=2.0)
        processes = Processes()
        self.addCleanup(processes.close)
        stream = source.open("rb")
        self.addCleanup(stream.close)
        video = VideoStream(processes, stream, (64, 32), 30, repeats=1)
        video.start()
        deadline = time.monotonic() + 5
        while video.queue.empty() and time.monotonic() < deadline:
            time.sleep(.01)
        started = time.monotonic()
        video.close()
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(video.thread is not None and video.thread.is_alive())
        self.assertEqual(processes.active, set())
        self.assertIsNone(video.process)

    def test_a_silent_decoder_reports_a_stall_instead_of_hanging(self):
        processes = Processes()
        self.addCleanup(processes.close)
        source = self.base / "clip.webm"
        source.write_bytes(b"stub")
        stream = source.open("rb")
        self.addCleanup(stream.close)
        video = VideoStream(processes, stream, (8, 8), 10, repeats=1, stall=0.2)
        video.process = processes.start([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                                        stdout=subprocess.PIPE, bufsize=0)
        video.started = True
        video.thread = threading.Thread(target=video._read, name="carousel-video-read")
        video.thread.start()
        with self.assertRaises(MediaError) as error:
            for _ in video.frames():
                pass
        self.assertIn("stalled", str(error.exception))
        video.close()
        self.assertEqual(processes.active, set())

    def test_a_truncated_frame_reports_corruption(self):
        processes = Processes()
        self.addCleanup(processes.close)
        source = self.base / "clip.webm"
        source.write_bytes(b"stub")
        stream = source.open("rb")
        self.addCleanup(stream.close)
        video = VideoStream(processes, stream, (8, 8), 10, repeats=1, stall=5)
        video.process = processes.start([sys.executable, "-B", "-c",
                                         "import sys; sys.stdout.buffer.write(b'12345')"],
                                        stdout=subprocess.PIPE, bufsize=0)
        video.started = True
        video.thread = threading.Thread(target=video._read, name="carousel-video-read")
        video.thread.start()
        with self.assertRaises(MediaError) as error:
            list(video.frames())
        self.assertIn("corrupt", str(error.exception))
        video.close()
        self.assertEqual(processes.active, set())

    def test_buffering_is_bounded_by_bytes_for_any_frame_size(self):
        source = self.base / "clip.webm"
        source.write_bytes(b"stub")
        stream = source.open("rb")
        self.addCleanup(stream.close)
        processes = Processes()
        self.addCleanup(processes.close)
        small = VideoStream(processes, stream, (64, 32), 25)
        large = VideoStream(processes, stream, (1280, 720), 25)
        self.assertGreaterEqual(small.depth, large.depth)
        for video in (small, large):
            self.assertGreaterEqual(video.depth, 1)
            self.assertLessEqual(video.depth, 12)
            self.assertGreaterEqual(video.ahead, 1)
            # The reader queue plus the presentation look-ahead are both bounded
            # by bytes, so a large window cannot multiply buffered pixels.
            self.assertLessEqual(video.depth * video.frame_bytes, 3 * 1024 * 1024)
            self.assertLessEqual(video.ahead * video.frame_bytes, 3 * 1024 * 1024)
        self.assertLess(large.depth, small.depth)
        self.assertLess(large.ahead, small.ahead)


class VideoDecoderTests(StorageCase):
    def add_video(self, name="clip.webm", **kwargs):
        source = self.base / name
        make_webm(source, **kwargs)
        processes = Processes()
        self.addCleanup(processes.close)
        stream, staged = self.library.temporary_upload()
        with stream:
            stream.write(source.read_bytes())
        info = probe(staged, processes)
        return self.library.add_upload(self.cid, name, staged, info)

    def events(self, decoder, timeout=15):
        result, deadline = [], time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = decoder.events.get(timeout=max(.01, deadline - time.monotonic()))
            result.append(event)
            if event[1] in ("done", "error"):
                return result
        self.fail("Decoder did not finish the video")

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_decoded_frames_are_rgb_and_timed_from_the_source(self):
        item = self.add_video(rate=10, duration=0.5)
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(item, (64, 32), dict(DEFAULTS, repeats=1))
        events = self.events(decoder)
        frames = [event for event in events if event[1] == "frame"]
        self.assertGreaterEqual(len(frames), 5)
        self.assertEqual({frame[2].mode for frame in frames}, {"RGB"})
        self.assertEqual({frame[2].size for frame in frames}, {(64, 32)})
        self.assertEqual({round(frame[3], 4) for frame in frames}, {0.1})

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_a_broken_hardware_backend_falls_back_to_software(self):
        item = self.add_video(rate=10, duration=0.4)
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        bogus = {"method": "definitely-not-a-real-hwaccel", "name": "bogus", "verified": True,
                 "reason": "test"}
        with patch("player.video_backend", return_value=dict(bogus)):
            decoder.request(item, (64, 32), dict(DEFAULTS, repeats=1))
            events = self.events(decoder)
        frames = [event for event in events if event[1] == "frame"]
        self.assertEqual(events[-1][1], "done", "software fallback must still play")
        self.assertGreaterEqual(len(frames), 4)
        with decoder.lock:
            self.assertIsNone(decoder.video)

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_a_cancelled_backend_probe_leaves_the_worker_usable(self):
        from multimedia import DetectionCancelled
        item = self.add_video(rate=10, duration=0.4)
        photo = self.add("photo.png", self.photo_bytes(), "png")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        probed = threading.Event()

        def cancelled(codec, ffmpeg=None, cancel=None):
            probed.set()
            raise DetectionCancelled()

        with patch("player.video_backend", side_effect=cancelled):
            decoder.request(item, (64, 32), dict(DEFAULTS, repeats=1))
            self.assertTrue(probed.wait(10), "backend probe never ran")
        self.assertTrue(decoder.thread.is_alive())
        decoder.request(photo, (64, 32), DEFAULTS)
        deadline = time.monotonic() + 15
        kinds = []
        while time.monotonic() < deadline and "done" not in kinds:
            kinds.append(decoder.events.get(timeout=5)[1])
        self.assertEqual(kinds[0], "frame")
        self.assertIn("done", kinds)

    def test_an_unexpected_decoder_failure_becomes_an_error_event(self):
        item = self.add("photo.png", self.photo_bytes(), "png")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        with patch("player.freeze", side_effect=RuntimeError("synthetic")):
            decoder.request(item, (64, 32), DEFAULTS)
            deadline = time.monotonic() + 10
            events = []
            while time.monotonic() < deadline:
                event = decoder.events.get(timeout=5)
                events.append(event)
                if event[1] in ("done", "error"):
                    break
        self.assertEqual(events[-1][1], "error")
        self.assertIn("Media could not be decoded (RuntimeError)", events[-1][2])
        decoder.request(item, (64, 32), DEFAULTS)
        self.assertEqual(decoder.events.get(timeout=10)[1], "frame")

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_switching_media_mid_video_leaves_nothing_running(self):
        item = self.add_video(rate=30, duration=4.0)
        photo = self.add("photo.png", self.photo_bytes(), "png")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(item, (64, 32), dict(DEFAULTS, repeats=5))
        self.assertEqual(decoder.events.get(timeout=15)[1], "frame")
        decoder.request(photo, (64, 32), DEFAULTS)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            event = decoder.events.get(timeout=5)
            if event[1] in ("done", "error"):
                break
        self.assertEqual(decoder.processes.active, set())
        self.assertIsNone(decoder.video)

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_the_frame_budget_stops_the_repeat_loop(self):
        item = self.add_video(rate=10, duration=0.3)
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(item, (48, 24), dict(DEFAULTS, repeats=3))
        frames = [event for event in self.events(decoder) if event[1] == "frame"]
        self.assertEqual(len(frames), 9)

    @staticmethod
    def photo_bytes():
        import io
        from PIL import Image
        stream = io.BytesIO()
        Image.new("RGB", (32, 24), "red").save(stream, format="PNG")
        return stream.getvalue()

    @unittest.skipUnless(ffmpeg_ready(), "Optional system FFmpeg unavailable")
    def test_the_selected_backend_is_logged_once_per_item(self):
        item = self.add_video(rate=10, duration=0.2)
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        import io
        import contextlib
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            decoder.request(item, (32, 32), dict(DEFAULTS, repeats=1))
            self.events(decoder)
        output = captured.getvalue()
        self.assertEqual(output.count("event=video_decoder"), 1)
        self.assertIn("codec=vp8", output)
        self.assertIn("backend=", output)
        self.assertIn("verified=", output)


class LookaheadBoundTests(unittest.TestCase):
    def test_the_decoded_frame_queue_is_a_small_bounded_buffer(self):
        self.assertGreaterEqual(LOOKAHEAD, 2)
        self.assertLessEqual(LOOKAHEAD, 16)

    def test_backend_for_a_missing_codec_is_software(self):
        self.assertIsNone(video_backend(None)["method"])
