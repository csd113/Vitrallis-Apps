"""Instrumentation-style performance regressions; no sleeps or wall-clock waits."""
import queue
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support import StorageCase, png_bytes
from player import Decoder
from settings import DEFAULTS
from ui import App


class DecoderStillCacheTests(StorageCase):
    def test_warm_still_cache_opens_media_once_per_item(self):
        item = self.add("photo.png", png_bytes(), "png")
        decoder = Decoder(self.library)
        self.addCleanup(decoder.close)

        def frame_event(generation):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    event = decoder.events.get(timeout=0.25)
                except queue.Empty:
                    continue
                if event[0] == generation and event[1] in ("frame", "error"):
                    return event
            self.fail("decoder produced no still frame")

        with patch.object(self.library, "open_item", wraps=self.library.open_item) as opened:
            kind = frame_event(decoder.request(item, (64, 32), dict(DEFAULTS)))[1]
            self.assertEqual(kind, "frame")
            self.assertEqual(opened.call_count, 1)
            # A warm still cache serves a repeated presentation without re-opening
            # (and therefore without re-decoding) the media file.
            kind = frame_event(decoder.request(item, (64, 32), dict(DEFAULTS)))[1]
            self.assertEqual(kind, "frame")
            self.assertEqual(opened.call_count, 1)


def headless_app(**attributes):
    """A real App with Tk-dependent collaborators replaced by recorders."""
    app = App.__new__(App)
    app.poll_id = None
    app.shutdown_requested = False
    app.pending = None
    app.pending_action = ""
    app.closing = False
    app.finished = False
    app.screen = "home"
    app.services = None
    app.revision = -1
    app.calls = []
    app.schedule = lambda: app.calls.append("schedule")
    app.update_address = lambda: app.calls.append("update_address")
    app.draw_folders = lambda: app.calls.append("draw_folders")
    for name, value in attributes.items():
        setattr(app, name, value)
    return app


class HomePollTests(unittest.TestCase):
    def test_folders_are_rebuilt_only_when_the_library_revision_changes(self):
        app = headless_app()
        library = SimpleNamespace(revision=3)
        app.services = SimpleNamespace(library=library)
        app.revision = 3
        app.poll()
        self.assertEqual(app.calls, ["update_address", "schedule"])
        library.revision = 4
        app.poll()
        self.assertEqual(app.calls, ["update_address", "schedule",
                                     "update_address", "draw_folders", "schedule"])

    def test_update_address_is_a_noop_before_the_server_exists(self):
        app = headless_app()
        with patch("ui.qr_image") as qr:
            app.update_address()
            app.services = SimpleNamespace(server=SimpleNamespace(urls=[]))
            app.qr_url = None
            app.update_address()
            qr.assert_not_called()

    def test_update_address_keeps_the_existing_qr_for_the_same_url(self):
        app = headless_app()
        app.services = SimpleNamespace(server=SimpleNamespace(urls=["http://10.0.0.2:8765"]))
        app.qr_url = "http://10.0.0.2:8765"
        with patch("ui.qr_image") as qr:
            app.update_address()
            qr.assert_not_called()


class PlaybackPollTests(unittest.TestCase):
    def playback_app(self, viewable=True):
        app = headless_app()
        app.root = SimpleNamespace(winfo_viewable=lambda: viewable)
        app.services = SimpleNamespace(library=SimpleNamespace(revision=0))
        app.screen = "playback"
        app.hidden = False
        app.playlist = SimpleNamespace(current={"id": "item"}, rng=None)
        return app

    def test_hidden_playback_stops_the_decoder_once_and_skips_ticks(self):
        app = self.playback_app(viewable=False)
        stops, events = [], []
        app.services.decoder = SimpleNamespace(stop=lambda: stops.append(1))
        app.load_item = lambda item: events.append("load:" + item["id"])
        app.track_conversion = lambda: events.append("conversion")
        app.playback_tick = lambda: events.append("tick")
        app.poll()
        app.poll()
        self.assertEqual(stops, [1])
        self.assertEqual(events, [])
        self.assertTrue(app.hidden)
        app.root = SimpleNamespace(winfo_viewable=lambda: True)
        app.poll()
        app.poll()
        self.assertEqual(events, ["load:item", "conversion", "tick", "conversion", "tick"])

    def test_returning_from_hidden_without_a_current_item_returns_home(self):
        app = self.playback_app(viewable=False)
        app.services.decoder = SimpleNamespace(stop=lambda: None)
        app.playlist.current = None

        def load(item):
            self.assertIsNone(item)
            app.calls.append("load")
            app.screen = "home"

        app.load_item = load
        app.track_conversion = lambda: app.calls.append("conversion")
        app.playback_tick = lambda: app.calls.append("tick")
        app.poll()
        app.root = SimpleNamespace(winfo_viewable=lambda: True)
        app.poll()
        self.assertEqual(app.calls, ["schedule", "load", "schedule"])

    def test_conversion_snapshot_is_read_at_most_once_per_second(self):
        app = self.playback_app()
        reads = []

        class Conversions:
            def snapshot(self):
                reads.append(1)
                return {"status": "idle", "message": "", "item": None, "replacement": None,
                        "name": "", "collection": None, "converter": ""}

        app.services.conversions = Conversions()
        app.conversion_poll = 0.0
        app.conversion_running = False
        app.conversion_last = ""
        app.conversion_message = ""
        app.conversion_label = None
        app.playback_tick = lambda: app.calls.append("tick")
        app.load_item = lambda item: app.calls.append("load")
        app.poll()
        self.assertEqual(len(reads), 1)
        app.poll()
        app.poll()
        self.assertEqual(len(reads), 1)


class ScheduleIntervalTests(unittest.TestCase):
    def test_idle_hidden_and_due_clock_intervals(self):
        app = App.__new__(App)
        app.finished = False
        app.hidden = False
        app.screen = "home"
        delays = []
        app.root = SimpleNamespace(after=lambda delay, callback: delays.append(delay))
        app.schedule()
        self.assertEqual(delays[-1], 400)
        app.screen = "settings"
        app.schedule()
        self.assertEqual(delays[-1], 400)
        app.screen = "closing"
        app.schedule()
        self.assertEqual(delays[-1], 50)
        app.screen = "playback"
        app.hidden = True
        app.schedule()
        self.assertEqual(delays[-1], 500)
        app.hidden = False
        app.clock = SimpleNamespace(delay_ms=lambda: 1)
        app.next_present = 0.0
        app.schedule()
        self.assertEqual(delays[-1], 4)
        app.next_present = time.monotonic() + 0.5
        app.schedule()
        self.assertGreaterEqual(delays[-1], 490)
