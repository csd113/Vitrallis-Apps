import importlib.util
import os
import sys
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui import BACK_FOCUS, EXIT_FOCUS, PULSE_FOCUS, PANELS, InteractionModel, PulseState


class InteractionTests(unittest.TestCase):
    def test_panel_expansion_collapse_and_focus_restore(self):
        model = InteractionModel(); model.focus = 2; model.open(2)
        self.assertEqual((model.expanded, model.focus), (2, BACK_FOCUS))
        self.assertTrue(model.close()); self.assertEqual((model.expanded, model.focus), (None, 2))

    def test_spatial_navigation_and_scroll(self):
        model = InteractionModel(); model.move("down"); self.assertEqual(model.focus, 1)
        model.move("right"); self.assertEqual(model.focus, 4)
        model.move("down"); self.assertEqual(model.focus, 3)
        model.open(3); model.move("down"); self.assertEqual(model.scroll, 36)
        model.move("up"); self.assertEqual(model.scroll, 0)

    def test_matching_press_release_and_drag_cancel(self):
        model = InteractionModel(); model.press("CPU")
        self.assertFalse(model.release("Memory")); model.press("CPU")
        self.assertTrue(model.release("CPU")); self.assertIsNone(model.pressed)

    def test_pulse_duration_duplicate_and_cancel(self):
        pulse = PulseState(); self.assertTrue(pulse.start(10.0)); self.assertFalse(pulse.start(10.1))
        self.assertAlmostEqual(pulse.progress(14.0), .5); self.assertTrue(pulse.cancel()); self.assertFalse(pulse.active)

    def test_imports_do_not_open_a_window(self):
        self.assertIsNotNone(importlib.util.find_spec("main"))
        import main
        self.assertTrue(callable(main.main))

    def test_demo_collector_is_explicit_and_deterministic_shape(self):
        from demo import DemoCollector
        sample = DemoCollector().collect()
        self.assertEqual(sample.network.primary.name, "wlan-demo")
        self.assertIn("demonstration", sample.cpu_model)


@unittest.skipUnless(os.environ.get("DISPLAY"), "GUI desktop/Xvfb unavailable")
class GuiSmokeTests(unittest.TestCase):
    def test_window_can_close(self):
        import tkinter as tk
        from ui import Dashboard
        root = tk.Tk(); root.withdraw()
        dashboard = Dashboard(root, tk)
        root.update(); dashboard.close()

    def test_close_during_animation(self):
        import tkinter as tk
        from ui import Dashboard
        root = tk.Tk(); root.withdraw()
        dashboard = Dashboard(root, tk)
        self.assertTrue(dashboard.model.pulse.start(time.monotonic()))
        dashboard._begin_pulse(); dashboard.close()
        self.assertTrue(dashboard.closed)


class FakeRenderer:
    def set_metrics(self, lines):
        self.metrics = lines

    def __init__(self, widget):
        self.renderer = 'Test hardware renderer'
        self.frames = []
        self.closed = False

    def draw(self, elapsed, width, height):
        self.frames.append((elapsed, width, height))

    def close(self):
        self.closed = True


@unittest.skipUnless(os.environ.get('DISPLAY') or os.environ.get('VITRALLIS_REQUIRE_GUI'), 'GUI unavailable')
class LayoutAndLifecycleTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from demo import DemoCollector
        from ui import Dashboard
        try:
            self.root = tk.Tk()
        except tk.TclError:
            if os.environ.get('VITRALLIS_REQUIRE_GUI'):
                raise
            self.skipTest('No usable Tk desktop')
        self.now = [10.0]
        self.root.geometry('480x272')
        self.app = Dashboard(self.root, tk, DemoCollector(), clock=lambda: self.now[0], demo=True,
                             renderer_factory=FakeRenderer)
        self.addCleanup(self.app.close)
        self.app.snapshot = DemoCollector().collect()
        self.app.last_snapshot_at = self.now[0]
        self.root.update_idletasks()
        self.app._render()

    def key(self, name, shift=False):
        from types import SimpleNamespace
        self.app._key(SimpleNamespace(keysym=name, state=1 if shift else 0))

    def test_all_cards_and_controls_keyboard_accessible(self):
        seen = set()
        for _ in range(7):
            seen.add(self.app.model.focus)
            self.key('Tab')
        self.assertEqual(seen, set(range(7)))
        self.app._activate('GPU')
        self.assertEqual(self.app.model.focus, BACK_FOCUS)
        self.key('Tab')
        self.assertEqual(self.app.model.focus, PULSE_FOCUS)
        self.key('Tab')
        self.assertEqual(self.app.model.focus, EXIT_FOCUS)
        self.key('Tab', True)
        self.assertEqual(self.app.model.focus, PULSE_FOCUS)
        self.key('Escape')
        self.assertEqual(self.app.model.focus, PANELS.index('GPU'))

    def test_summary_text_fits_cards_at_supported_sizes(self):
        for geometry in ('400x240', '480x272', '800x480'):
            self.root.geometry(geometry)
            self.root.update_idletasks()
            self.app._render()
            boxes = self.app._bounds()
            for name in PANELS:
                box = boxes[name]
                texts = []
                for item in self.app.canvas.find_all():
                    if self.app.canvas.type(item) != 'text': continue
                    x, y = self.app.canvas.coords(item)
                    if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                        bbox = self.app.canvas.bbox(item)
                        self.assertGreaterEqual(bbox[0], box[0], (geometry, name, bbox))
                        self.assertLessEqual(bbox[2], box[2], (geometry, name, bbox))
                        self.assertLessEqual(bbox[3], box[3], (geometry, name, bbox))
                        texts.append(bbox)
                for i, left in enumerate(texts):
                    for right in texts[i+1:]:
                        overlap = min(left[2], right[2]) > max(left[0], right[0]) and min(left[3], right[3]) > max(left[1], right[1])
                        self.assertFalse(overlap, (geometry, name, left, right))

    def test_long_detail_rows_are_measured_and_scroll_is_clamped(self):
        self.app.snapshot.cpu_model = 'Long CPU model with many words ' * 50
        for name in PANELS:
            self.app._activate(name)
            self.app._scroll(999999)
            self.root.update_idletasks()
            top, bottom = self.app.detail_canvas.yview()
            self.assertAlmostEqual(bottom, 1, places=2)
            self.assertLess(top, bottom)
            self.app._scroll(-999999)
            self.assertEqual(self.app.model.scroll, 0)
        self.app._activate('CPU')
        texts = [self.app.detail_canvas.bbox(item) for item in self.app.detail_canvas.find_all()
                 if self.app.detail_canvas.type(item) == 'text']
        # Heading/content pairs below the graph must never overlap vertically.
        for left, right in zip(texts[3:], texts[4:]):
            self.assertLessEqual(left[3], right[1])

    def test_pulse_is_foreground_capped_and_stops_without_redraw_loop(self):
        self.app._activate('pulse')
        renderer = self.app.renderer
        self.root.update_idletasks()
        self.assertTrue(self.app.pulse_layer.winfo_ismapped())
        self.assertEqual(len(renderer.frames), 1)
        for _ in range(5): self.app._render()
        self.assertEqual(len(renderer.frames), 1, 'Dashboard redraw must not submit animation frames')
        timer = self.app.pulse_after
        self.assertIsNotNone(timer)
        self.key('Escape')
        self.assertFalse(self.app.model.pulse.active)
        self.assertIsNone(self.app.pulse_after)
        self.assertNotIn(timer, self.app.after_ids)
        self.app._activate('pulse')
        self.now[0] = 19.0
        self.app._pulse_frame()
        self.assertFalse(self.app.model.pulse.active)
        self.app.close()
        self.assertTrue(renderer.closed)
        self.assertFalse(self.app.after_ids)

    def test_gpu_failure_is_visible_and_does_not_start_cpu_animation(self):
        from gpu import GpuUnavailable
        def failed_renderer(widget):
            raise GpuUnavailable('Software renderer rejected')
        self.app.renderer_factory = failed_renderer
        self.app._activate('pulse')
        self.assertFalse(self.app.model.pulse.active)
        self.assertIsNone(self.app.pulse_after)
        self.assertIn('Software renderer rejected', str(self.app._detail_lines('GPU')))
        self.assertEqual(self.app.model.expanded, PANELS.index('GPU'))

    def test_stale_gpu_samples_leave_gaps(self):
        from diagnostics import GpuReading
        from demo import DemoCollector
        sample = DemoCollector().collect()
        self.app.results.put_nowait(sample)
        self.app._drain_results()
        self.assertEqual(self.app.gpu_history.items(), (24.6,))
        sample = DemoCollector().collect()
        sample.gpu = None
        self.app.results.put_nowait(sample)
        self.app._drain_results()
        self.assertEqual(self.app.gpu_history.items(), (24.6, None))
        sample.gpu = GpuReading('Another GPU', 50, '/new/counter')
        self.app.results.put_nowait(sample)
        self.app._drain_results()
        self.assertEqual(self.app.gpu_history.items(), (50,))

    def test_cpu_and_gpu_names_remain_visible_without_utilization(self):
        from hardware import DeviceIdentity, HardwareInfo
        self.app.snapshot.cpu_percent = None
        self.app.snapshot.cpu_model = 'ARM Cortex-A72'
        self.app.snapshot.gpu = None
        self.app.snapshot.hardware = HardwareInfo(
            (DeviceIdentity('ARM Cortex-A72', 'Linux CPU device tree'),),
            (DeviceIdentity('ARM Mali-400', 'Linux GPU device tree'),))
        self.app._render()
        self.assertEqual(self.app._panel_summary('CPU')[1], 'ARM Cortex-A72')
        self.assertEqual(self.app._panel_summary('GPU'), ('—', 'ARM Mali-400'))
        names = [self.app.canvas.itemcget(item, 'text') for item in self.app.canvas.find_all()
                 if self.app.canvas.type(item) == 'text']
        self.assertIn('ARM Cortex-A72', names)
        self.assertIn('ARM Mali-400', names)

    def test_embedded_driver_board_and_soc_details_are_explicit(self):
        from hardware import DeviceIdentity, DriverInfo, HardwareInfo
        self.app.snapshot.hardware = HardwareInfo(
            gpus=(DeviceIdentity('ARM Mali-400', '/sys/device/compatible',
                                 driver=DriverInfo('mali', '/sys/device/driver', 'mali', 'r3p0', 'ABC123')),),
            displays=(DeviceIdentity('Display engine', '/sys/display',
                                     driver=DriverInfo('sun4i-drm', '/sys/display/driver')),),
            board=DeviceIdentity('NextThing C.H.I.P.', '/sys/firmware/devicetree/base/model'),
            soc=DeviceIdentity('Allwinner R8', '/sys/firmware/devicetree/base/compatible'),
            kernel_release='6.12.20-test',
            cpu_drivers=(DriverInfo('cpufreq-dt', '/sys/cpufreq/scaling_driver'),))
        gpu = dict(self.app._detail_lines('GPU'))
        self.assertIn('Module version: r3p0', gpu['GPU 1 driver'])
        self.assertIn('Source version ID: ABC123', gpu['GPU 1 driver'])
        self.assertIn('Module version: not exported', gpu['Display 1 driver'])
        self.assertEqual(gpu['Kernel'], '6.12.20-test')
        self.assertIn('select Pulse', gpu['OpenGL ES / userspace driver'])
        cpu = dict(self.app._detail_lines('CPU'))
        self.assertIn('NextThing C.H.I.P.', cpu['Board'])
        self.assertIn('Allwinner R8', cpu['SoC'])
        self.assertIn('cpufreq-dt', cpu['CPU frequency driver'])

    def test_all_detected_gpus_and_sources_are_listed_in_details(self):
        from hardware import DeviceIdentity, HardwareInfo
        self.app.snapshot.hardware = HardwareInfo(gpus=(
            DeviceIdentity('Integrated graphics with a long model name', 'Kernel source', aliases=('card0',)),
            DeviceIdentity('NVIDIA GeForce RTX 4070', 'PCI source')))
        self.app.snapshot.gpu = None
        details = str(self.app._detail_lines('GPU'))
        self.assertIn('Integrated graphics with a long model name', details)
        self.assertIn('NVIDIA GeForce RTX 4070', details)
        self.assertIn('Kernel source', details)
        self.assertIn('PCI source', details)
