import gc
import os
import signal
import threading
import time
import tkinter as tk
from unittest.mock import Mock, patch

from support import StorageCase, animated_webp_bytes, gif_bytes, png_bytes, webp_bytes
from convert import ConversionError
from player import GpuFrame
from settings import DEFAULTS
from ui import App, Services
from main import install_shutdown_handlers


class FakeConversions:
    def __init__(self):
        self.state = {"status": "idle", "message": "", "item": None, "replacement": None,
                      "name": "", "collection": None, "converter": "gif2webp"}
        self.started = []
        self.reads = 0
        self.closed = False

    def snapshot(self):
        self.reads += 1
        return dict(self.state)

    def start(self, cid, mid):
        if self.state["status"] == "running":
            raise ConversionError("Conversion already running", code=409)
        self.started.append((cid, mid))
        self.state.update(status="running", item=mid, collection=cid, name="animation.gif")
        return dict(self.state)

    def close(self):
        self.closed = True


class FailingConversions(FakeConversions):
    def start(self, cid, mid):
        raise ConversionError("Conversion already running", code=409)


class NativeTests(StorageCase):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            if os.environ.get("VITRALLIS_REQUIRE_GUI") == "1":
                raise
            self.skipTest("Graphical Tk unavailable: " + str(error))
        self.app = App(self.root, lambda: Services(self.paths, "127.0.0.1", 0))
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.cleanup_app)
        self.wait_for(lambda: self.app.services is not None)

    def wait_for(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(predicate(), "GUI operation timed out")
        self.assertEqual(self.errors, [])

    def cleanup_app(self):
        if not self.app.finished:
            self.app.close()
            self.wait_for(lambda: self.app.finished)
        self.app.finish()
        gc.collect()

    def tick(self):
        """Run one poll deterministically instead of waiting for the after() timer."""
        if self.app.poll_id is not None:
            self.root.after_cancel(self.app.poll_id)
            self.app.poll_id = None
        self.app.poll()

    def test_home_480_layout_large_touch_targets_and_keyboard_focus(self):
        self.root.update_idletasks()
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (480, 272))
        self.assertIn("http://127.0.0.1:", self.app.url_label.cget("text"))
        for button in self.app.folder_buttons:
            self.assertGreaterEqual(button.winfo_height(), 36)
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + 272)
        self.app.services.library.create("Long collection " + "W" * 40)
        self.app.services.library.create("Third collection")
        self.app.draw_folders()
        self.root.update()
        self.app.folder_buttons[0].focus_force()
        self.root.update()
        self.app.move_focus(1)
        self.assertEqual(self.root.focus_get(), self.app.folder_buttons[1])
        self.app.move_focus(1)
        self.assertEqual(self.app.page, 1)

    def test_prepared_gpu_frame_can_fall_back_to_tk(self):
        from PIL import Image
        self.app.canvas = tk.Canvas(self.app.frame)
        self.app.canvas.pack()
        self.app.image_id = self.app.canvas.create_image(0, 0)
        self.root.update_idletasks()
        self.app.close_gpu()
        self.app.present_frame(GpuFrame.from_image(Image.new("RGBA", (8, 8), "red")))
        self.assertIsNotNone(self.app.photo)

    def test_settings_fit_and_persist_and_invalid_input(self):
        self.app.settings_screen()
        self.root.update()
        self.assertLessEqual(self.app.save_button.winfo_rooty() + self.app.save_button.winfo_height(), self.root.winfo_rooty() + 272)
        self.app.seconds.set("invalid")
        self.app.save_settings()
        self.assertIsNone(self.app.pending)
        self.app.seconds.set("9")
        self.app.repeats.set("4")
        self.app.order.set("Shuffle")
        self.app.loop.set("Return to Main Menu")
        self.app.convert_gifs.set("Convert to WebP")
        self.app.save_settings()
        self.wait_for(lambda: self.app.pending is None)
        self.assertEqual(self.app.services.settings.snapshot(),
                         {"image_seconds": 9, "repeats": 4, "order": "shuffle", "loop": False,
                          "convert_gifs": True})
        self.app.escape()
        self.assertEqual(self.app.screen, "home")

    def test_empty_and_all_bad_playlists_return_with_explanation(self):
        self.app.play(self.cid)
        self.assertEqual(self.app.screen, "home")
        self.assertIn("Empty", self.app.home_notice)
        stream, staged = self.app.services.library.temporary_upload()
        with stream:
            stream.write(b"corrupt")
        self.app.services.library.add_upload(self.cid, "broken.png", staged, {"kind": "png"})
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.screen == "home")
        self.assertIn("No playable media", self.app.home_notice)

    def upload_to_services(self, name, raw, kind):
        stream, staged = self.app.services.library.temporary_upload()
        with stream:
            stream.write(raw)
        return self.app.services.library.add_upload(self.cid, name, staged, {"kind": kind})

    def test_native_gif_return_pause_previous_next_and_close(self):
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=False))
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.photo is not None)
        self.app.pause()
        photo = self.app.photo
        for _ in range(15):
            self.root.update()
            time.sleep(.02)
        self.assertIs(self.app.photo, photo)
        self.assertTrue(self.app.clock.paused)
        self.app.pause()
        self.wait_for(lambda: self.app.screen == "home")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=True))
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.photo is not None)
        first_generation = self.app.generation
        self.wait_for(lambda: self.app.generation > first_generation)
        self.assertEqual(self.app.screen, "playback")
        self.app.navigate(-1)
        self.assertGreater(self.app.generation, first_generation)
        self.app.navigate(1)
        self.app.escape()
        self.assertEqual(self.app.screen, "home")

    def test_gpu_present_pause_navigation_and_surface_failure_fallback(self):
        from gpu import GpuUnavailable
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        renderer = Mock(renderer="Mali-400")
        with patch("ui.ImageRenderer", return_value=renderer):
            self.app.play(self.cid)
            self.wait_for(lambda: renderer.present.called)
            self.assertIsNone(self.app.photo)
            self.app.pause()
            count = renderer.present.call_count
            for _ in range(5):
                self.root.update()
                time.sleep(.02)
            self.assertEqual(renderer.present.call_count, count)
            renderer.present.side_effect = GpuUnavailable("surface lost")
            self.app.pause()
            self.wait_for(lambda: self.app.photo is not None)
            self.assertIsNone(self.app.gpu_renderer)
            renderer.close.assert_called_once()
            self.app.navigate(1)
            self.app.escape()
            self.assertEqual(self.app.screen, "home")

    def test_close_during_startup_and_no_owned_threads(self):
        self.cleanup_app()
        root = tk.Tk()
        def slow_start():
            time.sleep(.2)
            return Services(self.paths, "127.0.0.1", 0)
        app = App(root, slow_start)
        app.close()
        deadline = time.monotonic() + 6
        while not app.finished and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        self.assertTrue(app.finished)
        app.finish()
        self.assertFalse([thread.name for thread in threading.enumerate() if thread.name.startswith("carousel-")])

    def test_missing_server_bind_keeps_native_library_usable(self):
        self.cleanup_app()
        with patch("web_server.BoundedServer", side_effect=OSError("Denied bind")):
            services = Services(self.paths, "127.0.0.1", 0)
        try:
            self.assertIn("unavailable", services.server.state)
            self.assertEqual(services.library.snapshot()[0]["name"], "Unsorted")
        finally:
            services.close()

    def test_shell_sigterm_requests_clean_shutdown(self):
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.photo is not None)
        previous = install_shutdown_handlers(self.app)
        try:
            signal.raise_signal(signal.SIGTERM)
            self.wait_for(lambda: self.app.finished)
            self.app.finish()
            self.assertFalse(self.app.services.decoder.thread.is_alive())
            self.assertFalse(self.app.services.server.thread.is_alive())
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    def test_animated_webp_uses_animation_pacing(self):
        stream, staged = self.app.services.library.temporary_upload()
        with stream:
            stream.write(animated_webp_bytes())
        self.app.services.library.add_upload(self.cid, "animation.webp", staged,
                                             {"kind": "webp", "animated": True})
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.animated)
        self.assertTrue(self.app.animated)

    def test_hidden_window_stops_decoder_once_and_reloads_on_return(self):
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.photo is not None)
        stop = Mock(wraps=self.app.services.decoder.stop)
        load = Mock(wraps=self.app.load_item)
        with patch.object(self.app.services.decoder, "stop", stop), \
                patch.object(self.app, "load_item", load):
            with patch.object(self.root, "winfo_viewable", return_value=False):
                self.tick()
                self.tick()
                self.assertTrue(self.app.hidden)
                self.assertEqual(stop.call_count, 1)
                self.assertFalse(load.called)
            with patch.object(self.root, "winfo_viewable", return_value=True):
                self.tick()
        self.assertFalse(self.app.hidden)
        self.assertTrue(load.called)
        self.assertEqual(load.call_args[0][0]["id"], self.app.playlist.current["id"])

    def test_overlay_visibility_flag_paused_and_focus(self):
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=True))
        self.app.play(self.cid)
        self.wait_for(lambda: self.app.photo is not None)
        self.assertTrue(self.app.overlay_visible)
        with patch.object(self.root, "focus_get", return_value=None):
            self.app.overlay_until = 0
            self.app.playback_tick()
        self.assertFalse(self.app.overlay_visible)
        self.assertEqual(self.app.overlay.winfo_manager(), "")
        self.app.pause()
        self.assertTrue(self.app.overlay_visible)
        with patch.object(self.root, "focus_get", return_value=None):
            self.app.overlay_until = 0
            self.app.playback_tick()
        self.assertTrue(self.app.overlay_visible)
        self.app.pause()  # resume
        focused = self.app.overlay.winfo_children()[0]
        with patch.object(self.root, "focus_get", return_value=focused):
            self.app.overlay_until = 0
            self.app.playback_tick()
        self.assertTrue(self.app.overlay_visible)

    def test_present_frame_converts_gpu_frame_once_and_skips_fitting_resize(self):
        from PIL import Image

        class CountingFrame(GpuFrame):
            converts = 0

            def convert(self, mode):
                CountingFrame.converts += 1
                return super().convert(mode)

        self.app.canvas = tk.Canvas(self.app.frame, width=64, height=48)
        self.app.canvas.pack()
        self.app.image_id = self.app.canvas.create_image(0, 0)
        self.root.update_idletasks()
        self.app.close_gpu()
        frame = CountingFrame.from_image(Image.new("RGBA", (8, 8), "red"))
        with patch("ui.display_copy") as copy:
            self.app.present_frame(frame)
            self.app.present_frame(self.app.last_frame)
            copy.assert_not_called()
        self.assertEqual(CountingFrame.converts, 1)

    def test_convert_action_eligibility_and_keyboard_binding(self):
        self.assertTrue(self.root.bind("<c>"))
        self.assertTrue(self.root.bind("<C>"))
        png = self.upload_to_services("photo.png", png_bytes(), "png")
        gif = self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=False))
        fake = FakeConversions()
        with patch.object(self.app.services, "conversions", fake):
            self.app.play(self.cid)
            self.wait_for(lambda: self.app.photo is not None)
            self.app.show_controls()
            self.root.update_idletasks()
            for button in (self.app.pause_button, self.app.convert_button):
                self.assertGreaterEqual(button.winfo_height(), 36)
            self.assertLessEqual(self.app.overlay.winfo_rooty() + self.app.overlay.winfo_height(),
                                 self.root.winfo_rooty() + 272)
            self.assertEqual(self.app.playlist.current["id"], png["id"])
            self.assertEqual(self.app.convert_button.cget("state"), "disabled")
            self.assertIn("GIF", self.app.conversion_label.cget("text"))
            self.app.convert_key(None)
            self.assertEqual(fake.started, [])
            self.app.navigate(1)
            self.assertEqual(self.app.playlist.current["id"], gif["id"])
            self.app.refresh_conversion_ui()
            self.assertEqual(self.app.convert_button.cget("state"), "normal")
            self.app.convert_key(None)
            self.assertEqual(fake.started, [(self.cid, gif["id"])])
            self.assertTrue(self.app.conversion_running)
            self.assertEqual(self.app.convert_button.cget("state"), "disabled")
            self.assertIn("Converting", self.app.conversion_label.cget("text"))

    def test_web_started_conversion_appears_in_the_overlay(self):
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=False))
        fake = FakeConversions()
        with patch.object(self.app.services, "conversions", fake):
            self.app.play(self.cid)
            self.wait_for(lambda: self.app.photo is not None)
            fake.state.update(status="running", item="remote", collection=self.cid, name="phone.gif")
            self.app.conversion_poll = 0.0
            self.app.track_conversion()
            self.assertTrue(self.app.conversion_running)
            self.assertIn("phone.gif", self.app.conversion_label.cget("text"))
            self.assertEqual(self.app.convert_button.cget("state"), "disabled")

    def test_conversion_start_failure_is_reported_inline(self):
        self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=False))
        fake = FailingConversions()
        with patch.object(self.app.services, "conversions", fake):
            self.app.play(self.cid)
            self.wait_for(lambda: self.app.photo is not None)
            self.app.show_controls()
            self.app.convert_current()
            self.assertEqual(fake.started, [])
            self.assertIn("Conversion already running", self.app.conversion_label.cget("text"))
            self.assertFalse(self.app.conversion_running)
            self.assertEqual(self.app.convert_button.cget("state"), "normal")

    def test_conversion_finish_resumes_at_replacement_once(self):
        gif = self.upload_to_services("animation.gif", gif_bytes(), "gif")
        self.app.services.settings.save(dict(DEFAULTS, repeats=1, loop=True))
        fake = FakeConversions()
        with patch.object(self.app.services, "conversions", fake):
            self.app.play(self.cid)
            self.wait_for(lambda: self.app.photo is not None)
            self.app.show_controls()
            self.app.convert_current()
            self.assertEqual(fake.started, [(self.cid, gif["id"])])
            replacement = self.upload_to_services("animation.webp", webp_bytes(), "webp")
            fake.state.update(status="ready", item=gif["id"], replacement=replacement["id"],
                              name="animation.gif", collection=self.cid, message="done")
            load = Mock(wraps=self.app.load_item)
            with patch.object(self.app, "load_item", load):
                self.app.conversion_poll = 0.0
                self.app.track_conversion()
                self.assertEqual(load.call_count, 1)
                self.assertEqual(self.app.playlist.current["id"], replacement["id"])
                self.assertFalse(self.app.conversion_running)
                self.assertIn("Converted", self.app.conversion_label.cget("text"))
                # The replacement is a WebP still, not another convertible GIF.
                self.assertEqual(self.app.convert_button.cget("state"), "disabled")
                self.app.conversion_poll = 0.0
                self.app.track_conversion()
                self.assertEqual(load.call_count, 1)  # terminal snapshot handled once
