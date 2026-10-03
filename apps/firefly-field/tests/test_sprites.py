import ctypes as c
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    'firefly_sprite_tests', Path(__file__).resolve().parents[1] / 'sprites.py')
sprites = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sprites)


def batch(maximum=2):
    draw = Mock(return_value=0)
    lib = SimpleNamespace(SDL_RenderGeometryRaw=draw,
                          SDL_ComposeCustomBlendMode=Mock(return_value=1))
    app = SimpleNamespace(sdl=SimpleNamespace(lib=lib), renderer=1,
                          texture=Mock(return_value=2))
    result = sprites.SpriteBatch(app, lambda name, w, h: (w, h, bytes(w*h*4)), maximum)
    return result, draw


class SpritePackingTests(unittest.TestCase):
    def test_fractional_destinations_and_center_rotation_match_sdl_quads(self):
        for angle, positions in [
            (0, [14, 6, 24, 6, 24, 14, 14, 14]),
            (90, [23, 5, 23, 15, 15, 15, 15, 5]),
        ]:
            with self.subTest(angle=angle):
                packed, _ = batch()
                packed.add('firefly', 20.1, 10.9, 10.7, 8.4, 128, angle)
                self.assertEqual(list(packed.positions[:8]), positions)
                expected_uv = (c.c_float * 8)(70/128, 2/68, 90/128, 2/68,
                                             90/128, 16/68, 70/128, 16/68)
                self.assertEqual(list(packed.coordinates[:8]), list(expected_uv))
                self.assertEqual(bytes(packed.colors[:16]), bytes([128])*16)
                self.assertEqual(list(packed.indices[:6]), [0, 1, 2, 0, 2, 3])

    def test_reused_slots_update_identity_alpha_and_position_without_reordering(self):
        packed, draw = batch()
        packed.add('glow', 20, 20, 4, 4, 0)
        packed.add('firefly', 40, 40, 4, 4, 255)
        self.assertEqual(bytes(packed.colors), bytes(16) + bytes([255])*16)
        packed.present()
        self.assertEqual(packed.count, 0)
        self.assertEqual(draw.call_args.args[8], 8)
        self.assertEqual(draw.call_args.args[10:12], (12, 2))
        packed.add('grass', 30, 30, 4, 4, 300)
        packed.add('firefly', 50, 50, 4, 4, -20)
        expected_uv = (c.c_float * 8)(70/128, 20/68, 88/128, 20/68,
                                     88/128, 62/68, 70/128, 62/68)
        self.assertEqual(list(packed.coordinates[:8]), list(expected_uv))
        self.assertEqual(bytes(packed.colors), bytes([255])*16 + bytes(16))
        self.assertEqual(list(packed.positions[:8]), [28, 28, 32, 28, 32, 32, 28, 32])
        self.assertEqual(list(packed.positions[8:]), [48, 48, 52, 48, 52, 52, 48, 52])
        self.assertEqual(list(packed.indices), [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7])

    def test_invalid_slots_and_unknown_atlas_names_fail_before_raw_writes(self):
        packed, _ = batch()
        for count in [-1, packed.maximum]:
            packed.count = count
            with patch.object(sprites.c, 'memset') as write:
                with self.assertRaisesRegex(RuntimeError, 'capacity exceeded'):
                    packed.add('glow', 0, 0, 1, 1)
                write.assert_not_called()
        packed.count = 0
        before = (bytes(packed.positions), bytes(packed.coordinates), bytes(packed.colors))
        with self.assertRaises(KeyError):
            packed.add('unknown', 0, 0, 1, 1)
        self.assertEqual(packed.count, 0)
        self.assertEqual((bytes(packed.positions), bytes(packed.coordinates), bytes(packed.colors)), before)


if __name__ == '__main__':
    unittest.main()
