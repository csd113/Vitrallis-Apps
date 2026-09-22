"""The web server is a background service: playback never waits for it."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import StorageCase, gif_bytes
from library import Library
from settings import Settings
from storage import Paths
from ui import Services
from web_server import WebServer

HEALTHY = {"vp8": True, "vp9": True, "webp": True, "webm": True, "ready": True,
           "missing": [], "accelerated": [],
           "acceleration": {"policy": "auto", "methods": [], "codecs": {}},
           "webm_note": "ok"}


def slow_probe(cancel=None, **kwargs):
    """A probe that honours the real cancellation contract, then reports healthy."""
    if cancel is not None:
        cancel.wait(30)
    return dict(HEALTHY)


class ServerLifecycleTests(StorageCase):
    def services(self, **kwargs):
        services = Services(self.paths, "127.0.0.1", 0, **kwargs)
        self.addCleanup(services.close)
        return services

    def test_slideshow_services_are_ready_without_waiting_for_the_server(self):
        with patch("web_server.lan_addresses", side_effect=lambda: time.sleep(2) or ["10.0.0.5"]), \
                patch("ui.capabilities", side_effect=slow_probe):
            started = time.monotonic()
            services = Services(self.paths, "0.0.0.0", 0)
            elapsed = time.monotonic() - started
            self.addCleanup(services.close)
            # Library, settings, decoder and conversion job are usable immediately.
            self.assertLess(elapsed, 1.5)
            self.assertEqual(services.server.state, WebServer.STARTING)
            self.assertEqual(services.server.urls, [])
            self.assertTrue(services.decoder.thread.is_alive())
            self.assertEqual(services.library.snapshot()[0]["name"], "Unsorted")
            self.assertIsNone(services.capabilities)
            self.assertEqual(services.server.wait_ready(timeout=10), WebServer.READY)
            self.assertTrue(services.server.urls[0].startswith("http://10.0.0.5:"))
            self.assertIsNone(services.capabilities)

    def test_a_failed_server_never_stops_local_playback(self):
        with patch("web_server.BoundedServer", side_effect=OSError("Denied bind")):
            services = Services(self.paths, "127.0.0.1", 0)
        self.addCleanup(services.close)
        self.assertEqual(services.server.wait_ready(timeout=10), WebServer.FAILED)
        self.assertIn("unavailable", services.server.detail)
        self.assertIn("Denied bind", services.server.detail)
        # The slideshow still decodes and presents media.
        item = self.add("animation.gif", gif_bytes(), "gif")
        services.decoder.request(item, (48, 24), {"image_seconds": 5, "repeats": 1,
                                                  "order": "ordered", "loop": False})
        deadline = time.monotonic() + 10
        kinds = []
        while time.monotonic() < deadline and "done" not in kinds:
            kinds.append(services.decoder.events.get(timeout=5)[1])
        self.assertEqual(kinds[0], "frame")
        self.assertIn("done", kinds)

    def test_server_state_machine_and_duplicate_start_refusal(self):
        services = self.services()
        self.assertEqual(services.server.wait_ready(timeout=10), WebServer.READY)
        self.assertTrue(services.server.available)
        self.assertTrue(services.server.urls)
        with self.assertRaises(RuntimeError):
            services.server.start_async()
        services.close()
        self.assertEqual(services.server.state, WebServer.STOPPED)
        with self.assertRaises(RuntimeError):
            services.server.start_async()

    def test_close_is_clean_and_leaves_no_owned_threads_or_children(self):
        services = self.services()
        services.server.wait_ready(timeout=10)
        server = services.server
        threads = {name: getattr(server, name) for name in
                   ("thread", "serve_thread", "address_thread")}
        self.assertTrue(all(thread is not None for thread in threads.values()), threads)
        threads["thread"].join(timeout=5)
        self.assertFalse(threads["thread"].is_alive())
        services.close()
        for name, thread in threads.items():
            self.assertFalse(thread.is_alive(), name)
        self.assertFalse(services.decoder.thread.is_alive())
        self.assertFalse(services.decoder.animation_cache.thread.is_alive())
        self.assertEqual(services.server.processes.active, set())
        self.assertFalse([thread.name for thread in threading.enumerate()
                          if thread.name.startswith("carousel-")])

    def test_closing_before_the_server_finishes_starting_is_safe(self):
        with patch("web_server.lan_addresses", side_effect=lambda: time.sleep(1) or []):
            server = WebServer(self.library, self.settings, "127.0.0.1", 0)
            server.start_async()
            server.close()
        self.assertEqual(server.state, WebServer.STOPPED)
        self.assertFalse([thread.name for thread in threading.enumerate()
                          if thread.name.startswith("carousel-http")])

    def test_capability_probing_never_blocks_construction_or_the_http_thread(self):
        blocked, release = threading.Event(), threading.Event()

        def gated_probe(cancel=None, **kwargs):
            blocked.set()
            release.wait(3)
            return dict(HEALTHY)

        self.addCleanup(release.set)
        slow_probe = gated_probe
        with patch("ui.capabilities", side_effect=slow_probe):
            started = time.monotonic()
            services = Services(self.paths, "127.0.0.1", 0)
            elapsed = time.monotonic() - started
            self.addCleanup(services.close)
            self.assertLess(elapsed, 1.5)
            self.assertTrue(blocked.wait(5))
            self.assertIsNone(services.capabilities)
            self.assertEqual(services.media_note(), "Checking multimedia decoders…")
            # The management UI is already answering while the probe still runs.
            self.assertEqual(services.server.wait_ready(timeout=10), WebServer.READY)
            release.set()
            deadline = time.monotonic() + 5
            while services.capabilities is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIsNotNone(services.capabilities)
            self.assertEqual(services.media_note(), "ok")

    def test_probe_failure_is_reported_and_never_propagates(self):
        with patch("ui.capabilities", side_effect=OSError("probe exploded")):
            services = Services(self.paths, "127.0.0.1", 0)
        self.addCleanup(services.close)
        deadline = time.monotonic() + 5
        while services.capability_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNone(services.capabilities)
        self.assertTrue(services.decoder.thread.is_alive())


class ServerSnapshotTests(unittest.TestCase):
    def test_snapshot_reports_every_lifecycle_field(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        paths = Paths({"HOME": str(Path(temp.name).resolve())})
        server = WebServer(Library(paths), Settings(paths.config), "127.0.0.1", 0)
        self.addCleanup(server.close)
        self.assertEqual(set(server.snapshot()), {"state", "detail", "error", "urls", "name"})
        self.assertEqual(server.snapshot()["state"], WebServer.STARTING)
        server.start_async()
        self.assertEqual(server.wait_ready(timeout=10), WebServer.READY)
        snapshot = server.snapshot()
        self.assertEqual(snapshot["state"], WebServer.READY)
        self.assertTrue(snapshot["urls"])
        self.assertEqual(snapshot["error"], "")
        server.close()
        self.assertEqual(server.snapshot()["state"], WebServer.STOPPED)
