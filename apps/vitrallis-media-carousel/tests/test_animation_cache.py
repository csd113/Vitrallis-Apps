import threading
import unittest
from unittest.mock import patch

from support import StorageCase, gif_bytes
from animation_cache import AnimationCache, NO_ROOM
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
    def cache(self, loader, limit=16):
        cache = AnimationCache(loader, lambda: limit)
        self.addCleanup(cache.close)
        return cache

    def ready(self, cache):
        with cache.condition:
            self.assertTrue(cache.condition.wait_for(
                lambda: all(key in cache.entries for key in cache.plan), timeout=3))

    @staticmethod
    def frames(item, size, gpu, cancel):
        yield GpuFrame((2, 1), b"\0" * 8), .04
        yield GpuFrame((2, 1), b"\1" * 8), .08

    def test_initial_ten_and_rolling_window_reuse_complete_animations(self):
        calls = []
        def loader(*args):
            calls.append(args[0]["id"])
            yield from self.frames(*args)
        cache = self.cache(loader)
        playlist = items(25)
        cache.update(playlist, (2, 1), True)
        self.ready(cache)
        self.assertEqual(calls, [str(i) for i in range(10)])
        saved = cache.wait(playlist[8], (2, 1), True, threading.Event())
        cache.update(playlist[7:], (2, 1), True)
        self.ready(cache)
        self.assertEqual(calls, [str(i) for i in range(17)])
        self.assertIs(cache.wait(playlist[8], (2, 1), True, threading.Event()), saved)
        self.assertEqual(len(cache.entries), 10)
        self.assertNotIn(cache.key(playlist[0], (2, 1), True), cache.entries)

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
        self.assertEqual(len(cache.entries), 2)

    def test_total_budget_evicts_and_retries_without_publishing_partial_gifs(self):
        with patch("animation_cache.TOTAL_BYTES", 32):
            cache = self.cache(self.frames)
            playlist = items(5)
            cache.update(playlist, (2, 1), True)
            self.ready(cache)
            self.assertEqual(cache._used(), 32)
            self.assertIs(cache.entries[cache.key(playlist[2], (2, 1), True)][0], NO_ROOM)
            cache.update(playlist[2:], (2, 1), True)
            self.ready(cache)
            self.assertEqual(cache._used(), 32)
            self.assertEqual(len(cache.wait(playlist[2], (2, 1), True, threading.Event())), 2)

    def test_per_gif_limit_falls_back_and_size_or_backend_change_invalidates(self):
        cache = self.cache(self.frames, limit=8)
        item = items(1)[0]
        cache.update([item], (2, 1), True)
        self.ready(cache)
        self.assertIsNone(cache.wait(item, (2, 1), True, threading.Event()))
        self.assertEqual(cache._used(), 0)
        cache.update([dict(item, size=2)], (1, 1), False)
        self.ready(cache)
        self.assertNotIn(cache.key(item, (2, 1), True), cache.entries)

    def test_foreground_restarts_preparation_with_newly_freed_memory(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def loader(item, *args):
            calls.append(item["id"])
            if item["id"] == "1" and calls.count("1") == 1:
                started.set()
                release.wait(3)
            yield from self.frames(item, *args)
        with patch("animation_cache.TOTAL_BYTES", 24):
            cache = self.cache(loader)
            self.addCleanup(release.set)
            playlist = items(2)
            cache.update(playlist, (2, 1), True)
            self.assertTrue(started.wait(3))
            cache.update(playlist[1:], (2, 1), True)
            release.set()
            self.ready(cache)
            self.assertEqual(len(cache.wait(playlist[1], (2, 1), True, threading.Event())), 2)
            self.assertEqual(calls, ["0", "1", "1"])

    def test_cancelled_preparation_never_publishes_stale_frames(self):
        started, release = threading.Event(), threading.Event()
        def loader(item, *args):
            if item["id"] == "0":
                started.set()
                release.wait(3)
            yield from self.frames(item, *args)
        cache = self.cache(loader)
        self.addCleanup(release.set)
        playlist = items(2)
        cache.update(playlist[:1], (2, 1), True)
        self.assertTrue(started.wait(3))
        cache.update(playlist[1:], (2, 1), True)
        release.set()
        self.ready(cache)
        self.assertEqual(list(cache.entries), [cache.key(playlist[1], (2, 1), True)])
        cache.clear()
        self.assertEqual(cache.entries, {})
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
    def test_first_frame_waits_for_complete_preparation_and_next_item_is_reused(self):
        first = self.add("first.gif", gif_bytes(), "gif")
        second = self.add("second.gif", gif_bytes(), "gif")
        started, release = threading.Event(), threading.Event()
        calls = []
        original = Decoder._prepare_animation
        def prepare(decoder, item, *args):
            calls.append(item["id"])
            for index, value in enumerate(original(decoder, item, *args)):
                yield value
                if item == first and index == 0:
                    started.set()
                    release.wait(3)
        with patch.object(Decoder, "_prepare_animation", prepare):
            decoder = Decoder(self.library)
            self.addCleanup(decoder.close)
            self.addCleanup(release.set)
            decoder.request(first, (48, 24), dict(DEFAULTS, repeats=1), gpu=True,
                            upcoming=[first, second])
            self.assertTrue(started.wait(3))
            self.assertTrue(decoder.events.empty())
            release.set()
            self.assertEqual([decoder.events.get(timeout=3)[1] for _ in range(4)],
                             ["frame", "frame", "frame", "done"])
            with decoder.animation_cache.condition:
                self.assertTrue(decoder.animation_cache.condition.wait_for(
                    lambda: len(decoder.animation_cache.entries) == 2, timeout=3))
            cached = decoder.animation_cache.wait(second, (48, 24), True, threading.Event())
            decoder.request(second, (48, 24), dict(DEFAULTS, repeats=1), gpu=True)
            event = decoder.events.get(timeout=3)
            self.assertIs(event[2], cached[0][0])
            self.assertEqual(calls, [first["id"], second["id"]])

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
                lambda: len(decoder.animation_cache.entries) == 2, timeout=3))
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
