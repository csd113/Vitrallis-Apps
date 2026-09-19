"""GPU policy tests and an opt-in real EGL integration check under Xvfb."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gpu import GpuUnavailable, PulseRenderer, hardware_renderer


class RendererPolicyTests(unittest.TestCase):
    def test_hidden_window_is_rejected_before_native_calls(self):
        from unittest.mock import Mock
        widget = Mock()
        widget.tk.call.return_value = 'x11'
        widget.winfo_viewable.return_value = False
        with patch.object(PulseRenderer, '_load') as load:
            with self.assertRaisesRegex(GpuUnavailable, 'visible window'):
                PulseRenderer(widget)
            load.assert_not_called()

    def test_rejects_software_and_unknown_renderers(self):
        for name in ('llvmpipe (LLVM 19)', 'softpipe', 'Software Rasterizer', '',
                     'SwiftShader', 'virgl', 'Unknown GPU', 'AMD software renderer', 'V3D software renderer'):
            self.assertFalse(hardware_renderer(name), name)

    def test_recognizes_target_and_common_hardware(self):
        for name in ('V3D 4.2', 'V3D 7.1', 'VC4 V3D 2.1', 'Mali-400 MP', 'lima', 'Panfrost Mali-G52', 'Adreno 630',
                     'Mesa Intel(R) UHD Graphics 620', 'AMD Radeon RX 6600', 'NVIDIA RTX 3080'):
            self.assertTrue(hardware_renderer(name), name)


@unittest.skipUnless(os.environ.get('VITRALLIS_REQUIRE_EGL') == '1', 'Opt-in EGL integration test')
class EglIntegrationTests(unittest.TestCase):
    def test_shader_resize_disposal_and_software_rejection(self):
        import tkinter as tk
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('480x272')
        surface = tk.Frame(root)
        surface.pack(fill='both', expand=True)
        root.update()
        # A real Xvfb context must reach the policy check and be rejected.
        with patch('gpu.hardware_renderer', return_value=False) as policy:
            with self.assertRaisesRegex(GpuUnavailable, 'Hardware rendering is unavailable'):
                PulseRenderer(surface)
            self.assertEqual(policy.call_count, 1)
        # Test-only bypass verifies GLSL and FFI on Mesa software CI. There is no
        # application flag or environment setting that permits CPU rendering.
        with patch('gpu.hardware_renderer', return_value=True):
            renderer = PulseRenderer(surface)
        self.addCleanup(renderer.close)
        for size in ('480x272', '800x480'):
            root.geometry(size)
            root.update()
            for elapsed in (0, 1, 4, 7.9):
                renderer.draw(elapsed, surface.winfo_width(), surface.winfo_height())
        renderer.close()
        renderer.close()
        self.assertIsNone(renderer.display)
        self.assertIsNone(renderer.xdisplay)

class OverlayTests(unittest.TestCase):
    def test_zero_load_is_visible_and_stale_samples_are_unavailable(self):
        from types import SimpleNamespace
        from ui import performance_lines
        sample = SimpleNamespace(cpu_percent=0, gpu=SimpleNamespace(percent=0), gpu_frequency_hz=297000000)
        self.assertEqual(performance_lines(sample), ('CPU 0.0%  GPU 0.0%', 'GPU 297 MHZ'))
        self.assertEqual(performance_lines(sample, stale=True), ('CPU --%  GPU --%', 'GPU -- MHZ'))

    def test_metrics_pixels_are_bounded_and_readable(self):
        from gpu import metrics_pixels
        width, height, raw = metrics_pixels(('CPU 40% GPU 72%', 'GPU 297 MHZ'))
        self.assertEqual(len(raw), width * height * 4)
        self.assertLessEqual(width, 460)
        self.assertIn(bytes((220,245,236,255)), raw)
