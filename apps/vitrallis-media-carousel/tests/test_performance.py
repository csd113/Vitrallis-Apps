"""Instrumentation-style performance regressions; no sleeps or wall-clock waits."""
import queue
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support import StorageCase, png_bytes
from player import Decoder, PlaybackClock
from settings import DEFAULTS
from ui import App, MAX_CATCHUP, STARVED_MS, WAKE_MS


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


class TickHarness:
    """Drive the real presentation loop with a controllable monotonic clock."""

    def tick_app(self, now):
        app = App.__new__(App)
        app.finished = False
        app.hidden = False
        app.screen = "playback"
        app.starved = False
        app.generation = 1
        app.animated = True
        app.overlay_visible = False
        app.overlay_until = 0.0
        app.root = SimpleNamespace(focus_get=lambda: None)
        app.canvas = SimpleNamespace(winfo_width=lambda: 480, winfo_height=lambda: 272)
        app.clock = PlaybackClock(lambda: now[0])
        app.services = SimpleNamespace(decoder=SimpleNamespace(events=queue.Queue(maxsize=64)))
        app.presented = []
        app.present_frame = app.presented.append
        app.advance = lambda *args: None
        app.close_gpu = lambda: None
        app.show_controls = lambda: None
        app.load_item = lambda item: None
        return app


class ScheduleIntervalTests(TickHarness, unittest.TestCase):
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
        app.starved = False
        app.clock = SimpleNamespace(delay_ms=lambda: 1)
        app.schedule()
        self.assertEqual(delays[-1], 4)

    def test_waiting_for_the_decoder_backs_the_poll_off(self):
        app = App.__new__(App)
        app.finished = False
        app.hidden = False
        app.screen = "playback"
        delays = []
        app.root = SimpleNamespace(after=lambda delay, callback: delays.append(delay))
        app.clock = SimpleNamespace(delay_ms=lambda: 1)
        app.starved = True
        app.schedule()
        self.assertEqual(delays[-1], STARVED_MS)
        # A due deadline with frames ready again returns to precise pacing.
        app.starved = False
        app.schedule()
        self.assertEqual(delays[-1], 4)

    def test_pacing_never_adds_processing_time_to_a_frame_delay(self):
        now = [10.0]
        app = self.tick_app(now)
        app.services.decoder.events.put((1, "frame", "a", 0.04))
        app.playback_tick()
        self.assertEqual(app.presented, ["a"])
        self.assertAlmostEqual(app.clock.deadline, 10.04)
        # A slow decode/present of 25 ms must not push the media timeline later.
        now[0] = 10.065
        app.services.decoder.events.put((1, "frame", "b", 0.04))
        app.playback_tick()
        self.assertEqual(app.presented, ["a", "b"])
        self.assertAlmostEqual(app.clock.deadline, 10.08)

    def test_late_frames_are_dropped_to_catch_up_without_looping_forever(self):
        now = [10.0]
        app = self.tick_app(now)
        app.services.decoder.events.put((1, "frame", "first", 0.04))
        app.playback_tick()
        self.assertEqual(app.presented, ["first"])
        # Playback stalled for a full second; every queued frame is already stale.
        now[0] = 11.0
        stale = MAX_CATCHUP + 4
        for index in range(stale):
            app.services.decoder.events.put((1, "frame", "stale%d" % index, 0.04))
        app.playback_tick()
        # Eight stale frames are dropped, the ninth is shown after resynchronising.
        self.assertEqual(app.presented, ["first", "stale%d" % MAX_CATCHUP])
        self.assertEqual(app.services.decoder.events.qsize(), stale - MAX_CATCHUP - 1)
        self.assertAlmostEqual(app.clock.deadline, now[0], places=3)

    def test_starved_polling_waits_for_the_decoder_instead_of_spinning(self):
        now = [10.0]
        app = self.tick_app(now)
        app.clock.deadline = 9.0  # The deadline is already due with nothing decoded.
        app.playback_tick()
        self.assertTrue(app.starved)
        self.assertEqual(app.presented, [])

    def test_variable_duration_frames_follow_the_media_timeline(self):
        now = [0.0]
        app = self.tick_app(now)
        durations = (0.04, 0.5, 0.04, 1.0)
        for index, seconds in enumerate(durations):
            app.services.decoder.events.put((1, "frame", index, seconds))
        expected, elapsed = [], 0.0
        for index, seconds in enumerate(durations):
            now[0] = elapsed          # Present each frame at its own start time.
            app.playback_tick()
            expected.append(index)
            elapsed += seconds
        self.assertEqual(app.presented, expected)
        self.assertAlmostEqual(app.clock.deadline, elapsed)

    def test_pause_freezes_the_deadline_and_resume_rebases_it(self):
        now = [5.0]
        app = self.tick_app(now)
        app.services.decoder.events.put((1, "frame", "a", 0.04))
        app.playback_tick()
        app.clock.toggle()
        now[0] = 30.0
        app.playback_tick()
        self.assertEqual(app.presented, ["a"])
        app.clock.toggle()
        self.assertAlmostEqual(app.clock.deadline, 30.04)
        now[0] = 30.05
        app.services.decoder.events.put((1, "frame", "b", 0.04))
        app.playback_tick()
        self.assertEqual(app.presented, ["a", "b"])

    def test_frames_from_an_abandoned_generation_are_never_presented(self):
        now = [1.0]
        app = self.tick_app(now)
        app.services.decoder.events.put((99, "frame", "stale-item", 0.04))
        app.services.decoder.events.put((1, "frame", "current", 0.04))
        app.playback_tick()
        self.assertEqual(app.presented, ["current"])


class LoadItemWakeTests(unittest.TestCase):
    """A hand-driven load must not wait out the previously scheduled poll."""

    def load_app(self, poll_id):
        app = App.__new__(App)
        app.poll_id = poll_id
        app.screen = "playback"
        app.gpu_renderer = None
        app.conversion_label = None
        item = {"id": "item-1", "kind": "png", "name": "photo.png"}
        app.playlist = SimpleNamespace(current=item, settings=dict(DEFAULTS),
                                       next=lambda: item, previous=lambda: item,
                                       upcoming=lambda: [])
        requests = []
        app.services = SimpleNamespace(decoder=SimpleNamespace(
            request=lambda *args, **kwargs: requests.append((args, kwargs)) or 7))
        app.canvas = SimpleNamespace(delete=lambda tag: None,
                                     itemconfigure=lambda *args, **kwargs: None,
                                     winfo_width=lambda: 480, winfo_height=lambda: 272)
        app.image_id = 1
        app.pause_button = SimpleNamespace(configure=lambda **kwargs: None)
        app.requests = requests
        app.calls = []
        app.timers = []

        def after(delay, callback):
            app.calls.append(("after", delay, callback))
            app.timers.append((delay, callback))
            return "new-timer"

        app.root = SimpleNamespace(
            after=after, after_cancel=lambda tid: app.calls.append(("cancel", tid)))
        return app

    def test_hand_driven_load_restarts_the_pending_timer(self):
        app = self.load_app("pending-timer")
        app.advance()
        self.assertEqual(len(app.requests), 1)
        self.assertEqual(app.calls, [("cancel", "pending-timer"), ("after", WAKE_MS, app.poll)])
        self.assertEqual(WAKE_MS, 4)
        self.assertEqual(app.poll_id, "new-timer")
        self.assertEqual(app.timers, [(WAKE_MS, app.poll)])

    def test_load_inside_poll_leaves_pacing_to_poll_end(self):
        app = self.load_app(None)
        app.advance()
        self.assertEqual(len(app.requests), 1)
        self.assertEqual(app.calls, [])
        self.assertIsNone(app.poll_id)
