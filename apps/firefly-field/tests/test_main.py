import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


MODULE = Path(__file__).resolve().parents[1] / "main.py"
sys.path.insert(0, str(MODULE.parent))
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

    def test_performance_meter_uses_cpu_deltas_and_real_gpu_counter_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc, sys_root = root / "proc", root / "sys"
            proc.mkdir()
            counter = sys_root / "class/drm/card0/device/gpu_busy_percent"
            counter.parent.mkdir(parents=True)
            proc.joinpath("stat").write_text("cpu  100 0 0 100 0\n", encoding="ascii")
            counter.write_text("47\n", encoding="ascii")
            meter = firefly.PerformanceMeter(proc, sys_root)
            initial = meter.sample(0)
            self.assertIsNone(initial.cpu_percent)
            self.assertEqual(initial.gpu_percent, 47.0)
            proc.joinpath("stat").write_text("cpu  180 0 0 120 0\n", encoding="ascii")
            measured = meter.sample(1)
            self.assertEqual(measured.cpu_percent, 80.0)
            self.assertEqual(measured.gpu_percent, 47.0)
            counter.write_text("101\n", encoding="ascii")
            self.assertIsNone(meter.sample(2).gpu_percent)

    def test_keyboard_controls_cover_the_complete_ambient_experience(self):
        app = object.__new__(firefly.FireflyApp)
        app.field = firefly.Field(50, seed=1)
        app.running, app.show_status, app.show_performance = True, False, False
        app.mood_index, app.wind_index = 0, 1
        app.field.update(.1)

        app.handle_key(firefly.SDLK_SPACE)
        self.assertTrue(app.field.paused)
        app.handle_key(ord("h"))
        self.assertTrue(app.show_status)
        app.handle_key(firefly.SDLK_UP)
        self.assertEqual(len(app.field.fireflies), 60)
        app.handle_key(firefly.SDLK_DOWN)
        self.assertEqual(len(app.field.fireflies), 50)
        app.handle_key(ord("a"))
        self.assertEqual(len(app.field.fireflies), 51)
        app.handle_key(ord("d"))
        self.assertEqual(len(app.field.fireflies), 50)
        app.field.change_population(firefly.MAX_FIREFLIES)
        app.handle_key(ord("a"))
        self.assertEqual(len(app.field.fireflies), firefly.MAX_FIREFLIES)
        initial_glow = app.field.glow
        app.handle_key(firefly.SDLK_LEFT)
        self.assertLess(app.field.glow, initial_glow)
        app.handle_key(firefly.SDLK_RIGHT)
        self.assertEqual(app.field.glow, initial_glow)
        app.handle_key(ord("p"))
        self.assertTrue(app.show_performance)
        app.handle_key(ord("c"))
        self.assertEqual(app.mood_index, 1)
        app.handle_key(ord("w"))
        self.assertEqual(app.wind_index, 2)
        app.handle_key(ord("r"))
        self.assertEqual(app.field.time, 0)
        app.handle_key(firefly.SDLK_ESCAPE)
        self.assertFalse(app.running)


class PolishTests(unittest.TestCase):
    def test_packaged_textures_decode_to_exact_dimensions(self):
        for name, width, height in (("meadow",480,272),("glow",64,64),("firefly",20,14),("grass",18,42)):
            with self.subTest(name=name):
                w,h,pixels=firefly.load_artwork(name,width,height)
                self.assertEqual((w,h,len(pixels)),(width,height,width*height*4))
        with self.assertRaises(RuntimeError):
            firefly.load_artwork("meadow",1,1)

    def test_artwork_rejects_truncated_and_trailing_streams(self):
        from unittest.mock import patch, mock_open
        import zlib
        valid = zlib.compress(bytes(16))
        for packed in (valid[:-1], valid + b"trailing", zlib.compress(bytes(17))):
            with self.subTest(packed=packed):
                with patch.object(Path, "open", mock_open(read_data=packed)):
                    with self.assertRaises(RuntimeError):
                        firefly.load_artwork("fixture", 2, 2)

    def test_guest_time_is_not_counted_twice(self):
        self.assertEqual(firefly.PerformanceMeter.cpu_totals("cpu 100 20 30 400 10 5 6 7 40 10"), (578,410))

    def test_software_gl_names_match_shell_without_false_positives(self):
        for name in ("llvmpipe (LLVM 19)","softpipe","SWR rasterizer","Mesa Software Rasterizer","swrast"):
            self.assertTrue(firefly.software_gl_renderer(name))
        for name in ("Apple M1", "Mali400", "Mesa Intel UHD", "unswrelated"):
            self.assertFalse(firefly.software_gl_renderer(name))

    def test_depth_order_survives_population_changes_and_reseed(self):
        field=firefly.Field()
        for change in (30,-10,500,-500):
            field.change_population(change)
            depths=[fly.depth for fly in field.fireflies]
            self.assertEqual(depths, sorted(depths))
        field.shooting_star=.1
        field.reseed()
        self.assertEqual(field.shooting_star,9)
        self.assertEqual([fly.depth for fly in field.fireflies],sorted(fly.depth for fly in field.fireflies))

    def test_font_contains_all_control_letters_and_backend_names(self):
        self.assertTrue(set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:-% ") <= firefly.FONT.keys())

    def test_keyboard_scatter_changes_center_insect_velocity(self):
        app=object.__new__(firefly.FireflyApp)
        app.field=firefly.Field()
        fly=app.field.fireflies[0]
        fly.x,fly.y,fly.vx,fly.vy=250,136,0,0
        app.handle_key(firefly.SDLK_RETURN)
        self.assertGreater(fly.vx,0)

    def test_toggle_repeat_and_pointer_leave(self):
        import ctypes as c
        class Events:
            def __init__(self, events): self.events=iter(events)
            def PollEvent(self, target):
                source=next(self.events,None)
                if source is None: return 0
                c.memmove(target,source,56)
                return 1
        repeated=(c.c_ubyte*56)()
        c.c_uint32.from_buffer(repeated).value=firefly.SDL_KEYDOWN
        repeated[13]=1
        c.c_int32.from_buffer(repeated,20).value=firefly.SDLK_SPACE
        leave=(c.c_ubyte*56)()
        c.c_uint32.from_buffer(leave).value=firefly.SDL_WINDOWEVENT
        leave[12]=firefly.SDL_WINDOWEVENT_LEAVE
        app=object.__new__(firefly.FireflyApp)
        app.field=firefly.Field()
        app.field.pointer=(50,50)
        app.sdl=Events([repeated,leave])
        app.events()
        self.assertFalse(app.field.paused)
        self.assertIsNone(app.field.pointer)

    def test_hardware_retry_and_fallback_policy(self):
        from unittest.mock import patch
        hardware=firefly.SDLRendererInfo();hardware.name=b'opengles2';hardware.flags=2
        software=firefly.SDLRendererInfo();software.name=b'software';software.flags=1
        class Drivers:
            def GetRenderDriverInfo(self, index, pointer):
                pointer._obj.name=b'software';pointer._obj.flags=1
                return 0
        for mode in ('auto','hardware','software'):
            with self.subTest(mode=mode):
                app=object.__new__(firefly.FireflyApp)
                app.sdl=Drivers();app.requested_renderer=mode
                calls=[]
                def attempt(index,actual,vsync):
                    calls.append((actual,vsync))
                    if actual=='hardware': raise RuntimeError('llvmpipe rejected')
                    return 1,2,software,(480,272)
                app.attempt_renderer=attempt
                app.snapshot=lambda *args: args
                with patch.object(firefly,'renderer_drivers',return_value=[(0,hardware),(1,software)]):
                    if mode=='hardware':
                        with self.assertRaisesRegex(RuntimeError,'llvmpipe rejected'): app.select_renderer()
                        self.assertEqual(calls,[('hardware',True),('hardware',False)])
                    else:
                        result=app.select_renderer()
                        self.assertEqual(result[2][0],'software')
                        if mode=='software': self.assertEqual(calls,[('software',False)])
                        else: self.assertIn('llvmpipe rejected',result[2][3])


if __name__ == "__main__":
    unittest.main()

class MenuTextureTests(unittest.TestCase):
    def test_cached_label_uploads_only_when_value_changes(self):
        from unittest.mock import Mock
        app = object.__new__(firefly.FireflyApp)
        app.sdl = Mock()
        app.renderer = 1
        app.textures = []
        app.text_cache = {}
        app.sdl.CreateTexture.side_effect = [10,11]
        app.sdl.UpdateTexture.return_value = 0
        app.sdl.SetTextureBlendMode.return_value = 0
        app.draw_text(10,10,'FPS: 30')
        app.draw_text(10,10,'FPS: 30')
        self.assertEqual(app.sdl.UpdateTexture.call_count,1)
        app.draw_text(10,10,'FPS: 31')
        self.assertEqual(app.sdl.UpdateTexture.call_count,2)
        app.sdl.DestroyTexture.assert_called_once_with(10)
        self.assertEqual(len(app.text_cache),1)
        self.assertEqual(len(app.textures),1)
