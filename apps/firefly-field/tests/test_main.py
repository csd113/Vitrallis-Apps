import importlib.util
from pathlib import Path
import sys
import unittest


MODULE = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("firefly_main", MODULE)
firefly = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = firefly
SPEC.loader.exec_module(firefly)


class FieldTests(unittest.TestCase):
    def test_population_is_bounded(self):
        field = firefly.Field(5)
        self.assertEqual(len(field.fireflies), firefly.MIN_FIREFLIES)
        field.change_population(1000)
        self.assertEqual(len(field.fireflies), firefly.MAX_FIREFLIES)

    def test_paused_field_does_not_advance(self):
        field = firefly.Field(40, seed=5)
        location = (field.fireflies[0].x, field.fireflies[0].y)
        field.paused = True
        field.update(.4)
        self.assertEqual(field.time, 0)
        self.assertEqual((field.fireflies[0].x, field.fireflies[0].y), location)

    def test_click_pulse_changes_nearby_insect_velocity(self):
        field = firefly.Field(30, seed=2)
        fly = field.fireflies[0]
        fly.x, fly.y, fly.vx, fly.vy = 210, 145, 0, 0
        field.pulse(200, 145)
        self.assertGreater(fly.vx, 0)

    def test_check_mode_needs_no_display(self):
        self.assertEqual(firefly.main(["--check"]), 0)

    def test_renderer_policy_requires_unambiguous_flags(self):
        info = firefly.SDLRendererInfo()
        info.flags = firefly.SDL_RENDERER_ACCELERATED
        self.assertTrue(firefly.valid_renderer("hardware", info))
        self.assertFalse(firefly.valid_renderer("software", info))
        info.flags |= firefly.SDL_RENDERER_SOFTWARE
        self.assertFalse(firefly.valid_renderer("hardware", info))

    def test_renderer_mode_parser_is_closed(self):
        self.assertEqual(firefly.parse_renderer("auto"), "auto")
        with self.assertRaises(ValueError):
            firefly.parse_renderer("vulkan")

    def test_keyboard_controls_cover_the_complete_ambient_experience(self):
        app = object.__new__(firefly.FireflyApp)
        app.field = firefly.Field(50, seed=1)
        app.running, app.show_status = True, False
        app.field.update(.1)

        app.handle_key(firefly.SDLK_SPACE)
        self.assertTrue(app.field.paused)
        app.handle_key(ord("h"))
        self.assertTrue(app.show_status)
        app.handle_key(firefly.SDLK_UP)
        self.assertEqual(len(app.field.fireflies), 60)
        app.handle_key(firefly.SDLK_DOWN)
        self.assertEqual(len(app.field.fireflies), 50)
        initial_glow = app.field.glow
        app.handle_key(firefly.SDLK_LEFT)
        self.assertLess(app.field.glow, initial_glow)
        app.handle_key(firefly.SDLK_RIGHT)
        self.assertEqual(app.field.glow, initial_glow)
        app.handle_key(ord("r"))
        self.assertEqual(app.field.time, 0)
        app.handle_key(firefly.SDLK_ESCAPE)
        self.assertFalse(app.running)


if __name__ == "__main__":
    unittest.main()
