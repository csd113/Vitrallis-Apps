import threading
import time
import unittest
from unittest.mock import patch

from support import StorageCase, gif_bytes
from animation_cache import WINDOW, AnimationCache
from player import Decoder, GpuFrame, Playlist
from settings import DEFAULTS


def items(count, kind="gif", animated=None):
    result = []
    for index in range(count):
        item = {"id": str(index), "size": 1, "kind": kind}
        if animated is not None:
            item["animated"] = animated
        result.append(item)
    return result


class CacheTests(unittest.TestCase):
    def cache(self, loader, limit=16, total=None):
        cache = AnimationCache(loader, lambda: limit, total or (lambda: 1 << 20))
        self.addCleanup(cache.close)
        return cache

    def idle(self, cache, timeout=3):
        """Wait until the background worker has nothing left to prepare."""
        with cache.condition:
            self.assertTrue(cache.condition.wait_for(
                lambda: cache.active is None and cache._next_key() is None, timeout=timeout))
        return cache

    def ready(self, cache, count=1, timeout=3):
        """Wait until at least `count` animations are prepared and nothing is queued."""
        with cache.condition:
            self.assertTrue(cache.condition.wait_for(
                lambda: cache.active is None and cache._next_key() is None
                and len(cache.entries) >= count, timeout=timeout))
        return cache

    @staticmethod
    def frames(item, size, gpu, cancel):
        yield GpuFrame((2, 1), b"\0" * 8), .04
        yield GpuFrame((2, 1), b"\1" * 8), .08

    def test_rolling_window_prefetches_upcoming_animations_and_reuses_them(self):
        calls = []
        def loader(*args):
            calls.append(args[0]["id"])
            yield from self.frames(*args)
        cache = self.cache(loader)
        playlist = items(25)
        cache.update(playlist, (2, 1), True)
        self.ready(cache, WINDOW - 1)
        # The item on screen is streamed by the decoder, not prefetched here.
        self.assertEqual(calls, [str(i) for i in range(1, WINDOW)])
        self.assertEqual(len(cache.entries), WINDOW - 1)
        saved = cache.take(playlist[8], (2, 1), True)
        self.assertEqual(len(saved), 2)
        cache.update(playlist[7:], (2, 1), True)
        self.ready(cache, WINDOW - 1)
        self.assertIs(cache.take(playlist[8], (2, 1), True), saved)
        self.assertNotIn(cache.key(playlist[0], (2, 1), True), cache.entries)
        self.assertGreaterEqual(len(calls), WINDOW - 1)

    def test_a_failed_prefetch_is_settled_and_never_retried(self):
        calls = []
        def loader(*args):
            calls.append(args[0]["id"])
            raise ValueError("corrupt")
            yield  # unreachable; keeps this a generator like a real loader
        cache = self.cache(loader)
        playlist = items(2)
        cache.update(playlist, (2, 1), True)
        self.idle(cache)
        key = cache.key(playlist[1], (2, 1), True)
        self.assertIn(key, cache.settled)
        self.assertNotIn(key, cache.entries)
        attempts = len(calls)
        self.assertEqual(attempts, 1)
        time.sleep(.2)
        self.assertEqual(len(calls), attempts)

    def test_store_publishes_frames_the_decoder_streamed(self):
        cache = self.cache(self.frames)
        playlist = items(3)
        cache.update(playlist, (2, 1), True)
        self.assertIsNone(cache.take(playlist[0], (2, 1), True))
        streamed = list(self.frames(playlist[0], (2, 1), True, threading.Event()))
        cache.store(playlist[0], (2, 1), True, streamed, 16)
        self.assertIs(cache.take(playlist[0], (2, 1), True), streamed)
        cache.clear()
        self.assertIsNone(cache.take(playlist[0], (2, 1), True))

    def test_plan_keeps_animated_gif_and_webp_and_skips_stills(self):
        cache = self.cache(self.frames)
        legacy_gif = {"id": "g", "size": 1, "kind": "gif"}
        animated_webp = {"id": "w", "size": 1, "kind": "webp", "animated": True}
        static_webp = {"id": "s", "size": 1, "kind": "webp", "animated": False}
        static_gif = {"id": "f", "size": 1, "kind": "gif", "animated": False}
        still = {"id": "p", "size": 1, "kind": "png", "animated": False}
        cache.update([legacy_gif, animated_webp, static_webp, static_gif, still], (2, 1), True)
        self.ready(cache)
        self.assertEqual(set(cache.plan), {cache.key(legacy_gif, (2, 1), True),
                                           cache.key(animated_webp, (2, 1), True)})
        self.assertEqual(len(cache.entries), 1)  # The foreground is decoder-owned.

    def test_total_budget_keeps_only_what_fits_and_stops_redoing_evicted_work(self):
        calls = []
        def loader(item, *args):
            calls.append(item["id"])
            yield from self.frames(item, *args)
        cache = self.cache(loader, total=lambda: 32)
        playlist = items(5)
        cache.update(playlist, (2, 1), True)
        self.idle(cache)
        self.assertLessEqual(cache._used(), 32)
        self.assertEqual(len(cache.entries), 2)
        self.assertIn(cache.key(playlist[4], (2, 1), True), cache.entries)
        self.assertEqual(sorted(calls), ["1", "2", "3", "4"])
        # Rolling the window forward must not decode the same animation over and
        # over just to evict it again; each item is prepared at most once per window.
        cache.update(playlist[2:], (2, 1), True)
        self.idle(cache)
        self.assertNotIn(cache.key(playlist[1], (2, 1), True), cache.entries)
        self.assertEqual(sorted(calls), ["1", "2", "3", "4"])
        self.assertLessEqual(cache._used(), 32)

    def test_a_too_large_animation_is_not_decoded_again_on_the_next_visit(self):
        calls = []
        def loader(item, *args):
            calls.append(item["id"])
            yield from self.frames(item, *args)
        cache = self.cache(loader, limit=8)  # Fits one frame, never both.
        playlist = items(2)
        cache.update(playlist, (2, 1), True)
        self.idle(cache)
        self.assertEqual(calls, ["1"])
        self.assertIn(cache.key(playlist[1], (2, 1), True), cache.settled)
        self.assertIsNone(cache.take(playlist[1], (2, 1), True))
        # A second navigation must not repeat the work that already failed.
        cache.update(playlist, (2, 1), True)
        with cache.condition:
            cache.condition.wait_for(
                lambda: cache.active is None and cache._next_key() is None, timeout=2)
        self.assertEqual(calls, ["1"])

    def test_the_foreground_entry_is_never_evicted(self):
        cache = self.cache(self.frames, limit=16, total=lambda: 8)
        playlist = items(3)
        cache.update(playlist, (2, 1), True)
        streamed = list(self.frames(playlist[0], (2, 1), True, threading.Event()))
        cache.store(playlist[0], (2, 1), True, streamed, 16)
        with cache.condition:
            cache._evict()
            self.assertIn(cache.key(playlist[0], (2, 1), True), cache.entries)

    def test_size_or_backend_change_invalidates_prepared_frames(self):
        cache = self.cache(self.frames)
        item = items(1)[0]
        cache.update([item], (2, 1), True)
        cache.store(item, (2, 1), True, list(self.frames(item, (2, 1), True, threading.Event())), 16)
        self.assertIsNotNone(cache.take(item, (2, 1), True))
        cache.update([item], (1, 1), False)
        self.assertIsNone(cache.take(item, (2, 1), True))
        self.assertIsNone(cache.take(item, (1, 1), False))

    def test_cancelled_preparation_never_publishes_stale_frames(self):
        started, release = threading.Event(), threading.Event()
        def loader(item, *args):
            if item["id"] == "1":
                started.set()
                release.wait(3)
            yield from self.frames(item, *args)
        cache = self.cache(loader)
        self.addCleanup(release.set)
        playlist = items(4)
        cache.update([playlist[0], playlist[1]], (2, 1), True)
        self.assertTrue(started.wait(3))
        # Navigating away cancels the obsolete job before it can be published.
        cache.update([playlist[0], playlist[2]], (2, 1), True)
        release.set()
        self.ready(cache, count=1)
        self.assertNotIn(cache.key(playlist[1], (2, 1), True), cache.entries)
        self.assertIsNotNone(cache.take(playlist[2], (2, 1), True))
        cache.clear()
        self.assertEqual(cache.entries, {})
        cache.close()
        self.assertFalse(cache.thread.is_alive())

    def test_prefetch_steps_aside_while_the_foreground_is_streamed(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def loader(item, *args):
            calls.append(item["id"])
            started.set()
            release.wait(3)
            yield from self.frames(item, *args)
        cache = self.cache(loader)
        self.addCleanup(release.set)
        cache.foreground_busy(True)
        cache.update(items(2), (2, 1), True)
        self.assertTrue(started.wait(3))
        self.assertFalse(release.is_set())
        cache.foreground_busy(False)
        release.set()
        self.ready(cache)
        self.assertEqual(calls, ["1"])

    def test_close_and_clear_are_idempotent(self):
        cache = self.cache(self.frames)
        cache.update(items(3), (2, 1), True)
        cache.clear()
        self.assertEqual(cache.entries, {})
        cache.close()
        cache.close()
        self.assertFalse(cache.thread.is_alive())

    def test_lookahead_preserves_shuffle_and_ordered_loop_sequence(self):
        playlist = Playlist(items(12), dict(DEFAULTS, order="ordered"))
        for _ in range(10):
            playlist.next()
        self.assertEqual([item["id"] for item in playlist.upcoming()], ["9", "10", "11", "0", "1", "2", "3", "4", "5", "6"])
        playlist.settings["order"] = "shuffle"
        state = playlist.rng.getstate()
        self.assertEqual([item["id"] for item in playlist.upcoming()], ["9", "10", "11"])
        self.assertEqual(playlist.rng.getstate(), state)

    def test_lookahead_window_counts_animated_webp_and_gif(self):
        sequence = [{"id": "p", "kind": "png", "animated": False}]
        sequence += [{"id": "g%d" % index, "kind": "gif"} for index in range(6)]
        sequence += [{"id": "s", "kind": "webp", "animated": False}]
        sequence += [{"id": "w%d" % index, "kind": "webp", "animated": True} for index in range(6)]
        playlist = Playlist(sequence, dict(DEFAULTS))
        upcoming = playlist.upcoming()
        self.assertEqual([item["id"] for item in upcoming],
                         ["p", "g0", "g1", "g2", "g3", "g4", "g5", "s", "w0", "w1", "w2", "w3"])
        self.assertEqual(upcoming[-1]["id"], "w3")


class PlaybackPreparationTests(StorageCase):
    def events(self, decoder, count, timeout=10):
        result = []
        for _ in range(count):
            result.append(decoder.events.get(timeout=timeout))
        return result

    def test_the_first_frame_is_not_held_back_by_full_preparation(self):
        item = self.add("animation.gif", gif_bytes(), "gif")
        gate, release = threading.Event(), threading.Event()
        original = Decoder._animation_frames
        def slow(decoder, source, size, gpu, cancel, deadline=None):
            for index, value in enumerate(original(decoder, source, size, gpu, cancel, deadline)):
                yield value
                if index == 0:
                    gate.set()
                    release.wait(3)
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        self.addCleanup(release.set)
        with patch.object(Decoder, "_animation_frames", slow):
            decoder.request(item, (48, 24), dict(DEFAULTS, repeats=1))
            # One frame on screen while the rest of the animation is still decoding.
            self.assertEqual(decoder.events.get(timeout=3)[1], "frame")
            self.assertTrue(gate.wait(3))
            release.set()
            self.assertEqual([event[1] for event in self.events(decoder, 2)], ["frame", "frame"])

    def test_lookahead_preparation_is_reused_by_the_decoder(self):
        first = self.add("first.gif", gif_bytes(), "gif")
        second = self.add("second.gif", gif_bytes(), "gif")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(first, (48, 24), dict(DEFAULTS, repeats=1), gpu=True,
                        upcoming=[first, second])
        self.assertEqual([event[1] for event in self.events(decoder, 4)],
                         ["frame", "frame", "frame", "done"])
        key = decoder.animation_cache.key(second, (48, 24), True)
        with decoder.animation_cache.condition:
            self.assertTrue(decoder.animation_cache.condition.wait_for(
                lambda: key in decoder.animation_cache.entries, timeout=5))
        cached = decoder.animation_cache.take(second, (48, 24), True)
        decoder.request(second, (48, 24), dict(DEFAULTS, repeats=1), gpu=True)
        self.assertIs(decoder.events.get(timeout=3)[2], cached[0][0])

    def test_a_played_animation_is_recorded_for_the_next_visit(self):
        item = self.add("clip.gif", gif_bytes(), "gif")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(item, (48, 24), dict(DEFAULTS, repeats=2))
        self.assertEqual([event[1] for event in self.events(decoder, 7)],
                         ["frame", "frame", "frame"] * 2 + ["done"])
        recorded = decoder.animation_cache.take(item, (48, 24), False)
        self.assertEqual(len(recorded), 3)
        decoder.request(item, (48, 24), dict(DEFAULTS, repeats=1))
        event = decoder.events.get(timeout=3)
        self.assertIs(event[2], recorded[0][0])

    def test_deleted_prefetched_item_is_not_played_from_memory(self):
        first = self.add("first.gif", gif_bytes(), "gif")
        second = self.add("second.gif", gif_bytes(), "gif")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(first, (48, 24), dict(DEFAULTS, repeats=1), upcoming=[first, second])
        for _ in range(4):
            decoder.events.get(timeout=3)
        with decoder.animation_cache.condition:
            self.assertTrue(decoder.animation_cache.condition.wait_for(
                lambda: len(decoder.animation_cache.entries) == 1, timeout=3))
        (self.paths.media / second["id"]).unlink()
        decoder.request(second, (48, 24), DEFAULTS)
        self.assertEqual(decoder.events.get(timeout=3)[1], "error")

    def test_resized_prefetched_file_is_rejected_before_cached_playback(self):
        item = self.add("animation.gif", gif_bytes(), "gif")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        decoder.request(item, (48, 24), dict(DEFAULTS, repeats=1))
        for _ in range(4):
            decoder.events.get(timeout=3)
        with (self.paths.media / item["id"]).open("ab") as stream:
            stream.write(b"changed")
        decoder.request(item, (48, 24), DEFAULTS)
        event = decoder.events.get(timeout=3)
        self.assertEqual(event[1], "error")
        self.assertIn("size", event[2])

    def test_rapid_navigation_leaves_nothing_decoding(self):
        first = self.add("first.gif", gif_bytes(), "gif")
        second = self.add("second.gif", gif_bytes(), "gif")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)
        for _ in range(10):
            decoder.request(first, (48, 24), dict(DEFAULTS, repeats=50), upcoming=[first, second])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            generation, kind, _, _ = decoder.events.get(timeout=1)
            if generation == decoder.generation or kind == "error":
                break
        decoder.stop()
        self.assertTrue(decoder.events.empty(), "obsolete frames stay queued")
        with decoder.animation_cache.condition:
            self.assertTrue(decoder.animation_cache.condition.wait_for(
                lambda: decoder.animation_cache.active is None, timeout=3))
        self.assertEqual(decoder.animation_cache.entries, {})
