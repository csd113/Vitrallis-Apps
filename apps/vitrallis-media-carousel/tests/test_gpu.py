import ctypes as c
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import Mock, patch
import unittest

from PIL import Image
from gpu import ImageRenderer, GpuUnavailable, hardware_renderer
from player import GpuFrame


class RendererTests(unittest.TestCase):
    def renderer(self):
        renderer = object.__new__(ImageRenderer)
        renderer.gl = Mock()
        renderer.gl.glGetError.return_value = 0
        renderer.egl = Mock()
        renderer.display = renderer.surface = renderer.context = 1
        renderer.texture = c.c_uint(1)
        renderer.max_texture = c.c_int(2048)
        renderer.image_size = None
        renderer.image_shape = None
        return renderer

    def test_cpu_rasterizer_is_not_claimed_as_hardware(self):
        self.assertTrue(hardware_renderer('Mali-400 (lima)'))
        self.assertFalse(hardware_renderer('llvmpipe (LLVM)'))
        self.assertFalse(hardware_renderer('unknown'))

    def test_texture_reused_and_gpu_viewport_fits_aspect_ratio(self):
        renderer = self.renderer()
        image = Image.new('RGBA', (800, 400), (255, 0, 0, 128))
        renderer.present(image, 480, 272)
        renderer.present(image, 480, 272)
        self.assertEqual(renderer.gl.glTexImage2D.call_count, 1)
        self.assertEqual(renderer.gl.glTexSubImage2D.call_count, 1)
        # RGBA frames upload as RGBA; opaque RGB frames keep their own format.
        self.assertEqual(renderer.gl.glTexImage2D.call_args[0][2], 0x1908)
        self.assertEqual(renderer.gl.glTexImage2D.call_args[0][6], 0x1908)
        renderer.present(Image.new('RGB', (800, 400)), 480, 272)
        self.assertEqual(renderer.gl.glTexImage2D.call_count, 2)
        self.assertEqual(renderer.gl.glTexImage2D.call_args[0][2], 0x1907)
        self.assertEqual(renderer.gl.glTexImage2D.call_args[0][6], 0x1907)
        renderer.present(Image.new('RGB', (800, 400)), 480, 272)
        self.assertEqual(renderer.gl.glTexSubImage2D.call_count, 2)
        renderer.gl.glViewport.assert_called_with(0, 16, 480, 240)
        self.assertEqual(renderer.gl.glDrawArrays.call_count, 4)

    def test_no_channel_conversion_happens_on_the_gpu_path(self):
        renderer = self.renderer()
        frame = GpuFrame.from_image(Image.new('RGB', (32, 16), 'red'), mode='RGB')
        image = frame.image()
        with patch.object(Image.Image, 'convert', side_effect=AssertionError('converted')):
            for _ in range(3):
                renderer.present(frame, 480, 272)
        self.assertEqual((image.size, image.mode), ((32, 16), 'RGB'))
        self.assertEqual(renderer.gl.glTexImage2D.call_count, 1)
        self.assertEqual(renderer.gl.glTexSubImage2D.call_count, 2)

    def test_upload_failure_oversize_and_surface_loss_trigger_fallback(self):
        renderer = self.renderer()
        renderer.max_texture.value = 16
        with self.assertRaises(GpuUnavailable):
            renderer.present(Image.new('RGB', (17, 4)), 480, 272)
        renderer.max_texture.value = 2048
        renderer.gl.glGetError.return_value = 0x0505
        with self.assertRaises(GpuUnavailable):
            renderer.present(Image.new('RGB', (10, 10)), 480, 272)
        renderer.gl.glGetError.return_value = 0
        renderer.egl.eglSwapBuffers.return_value = 0
        with self.assertRaises(GpuUnavailable):
            renderer.present(Image.new('RGB', (10, 10)), 480, 272)

@unittest.skipUnless(os.environ.get('VITRALLIS_REQUIRE_EGL') == '1', 'Opt-in EGL integration test')
class EglIntegrationTests(unittest.TestCase):
    def test_real_texture_orientation_resize_and_software_rejection(self):
        import tkinter as tk
        from unittest.mock import patch
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry('480x272')
        surface = tk.Frame(root)
        surface.pack(fill='both', expand=True)
        root.update()
        with patch('gpu.hardware_renderer', return_value=False) as policy:
            with self.assertRaises(GpuUnavailable):
                ImageRenderer(surface)
            self.assertEqual(policy.call_count, 1)
        # Test-only Mesa bypass checks actual EGL/GL calls, never a shipping mode.
        with patch('gpu.hardware_renderer', return_value=True):
            renderer = ImageRenderer(surface)
        self.addCleanup(renderer.close)
        image = Image.new('RGBA', (48, 24), 'red')
        image.paste('blue', (0, 12, 48, 24))
        read = renderer.gl.glReadPixels
        read.restype = None
        read.argtypes = [c.c_int, c.c_int, c.c_int, c.c_int, c.c_uint, c.c_uint, c.c_void_p]
        with patch.object(renderer.egl, 'eglSwapBuffers', return_value=1):
            renderer.present(image, 480, 272)
            for position, expected in (((216, 124), (0, 0, 255)), ((216, 147), (255, 0, 0)), ((0, 0), (0, 0, 0))):
                pixel = (c.c_ubyte * 4)()
                read(*position, 1, 1, 0x1908, 0x1401, pixel)
                self.assertEqual(tuple(pixel)[:3], expected)
        root.geometry('800x480')
        root.update()
        renderer.present(image, 800, 480)
        renderer.clear()
        renderer.close()
        renderer.close()
        self.assertIsNone(renderer.display)
