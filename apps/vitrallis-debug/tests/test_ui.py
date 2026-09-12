import importlib.util
import os
import sys
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui import InteractionModel, PulseState


class InteractionTests(unittest.TestCase):
    def test_panel_expansion_collapse_and_focus_restore(self):
        model = InteractionModel(); model.focus = 2; model.open(2)
        self.assertEqual((model.expanded, model.focus), (2, 6))
        self.assertTrue(model.close()); self.assertEqual((model.expanded, model.focus), (None, 2))

    def test_spatial_navigation_and_scroll(self):
        model = InteractionModel(); model.move("right"); self.assertEqual(model.focus, 1)
        model.move("down"); self.assertEqual(model.focus, 3)
        model.open(3); model.move("down"); self.assertEqual(model.scroll, 36)
        model.move("up"); self.assertEqual(model.scroll, 0)

    def test_matching_press_release_and_drag_cancel(self):
        model = InteractionModel(); model.press("CPU")
        self.assertFalse(model.release("Memory")); model.press("CPU")
        self.assertTrue(model.release("CPU")); self.assertIsNone(model.pressed)

    def test_pulse_duration_duplicate_and_cancel(self):
        pulse = PulseState(); self.assertTrue(pulse.start(10.0)); self.assertFalse(pulse.start(10.1))
        self.assertAlmostEqual(pulse.progress(11.0), .5); self.assertTrue(pulse.cancel()); self.assertFalse(pulse.active)

    def test_imports_do_not_open_a_window(self):
        self.assertIsNotNone(importlib.util.find_spec("main"))
        import main
        self.assertTrue(callable(main.main))

    def test_demo_collector_is_explicit_and_deterministic_shape(self):
        from demo import DemoCollector
        sample = DemoCollector().collect()
        self.assertEqual(sample.network.primary.name, "wlan-demo")
        self.assertIn("demonstration", sample.cpu_model)


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt", "GUI desktop/Xvfb unavailable")
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
