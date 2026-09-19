#!/usr/bin/env python3
"""A calm, GPU-friendly SDL2 firefly field for small Vitrallis displays.

Packaged artwork is uploaded once as small RGBA textures.  The frame loop only updates
insect state and issues SDL texture/primitive draws; it never uploads a full
CPU framebuffer.  SDL's accelerated renderer is requested first and a normal
SDL renderer is used when the platform has no accelerated driver.
"""
from __future__ import annotations

import ctypes as c
from ctypes.util import find_library
from dataclasses import dataclass
import math
from pathlib import Path
import random
import re
import zlib
import sys
import time
from sprites import SpriteBatch
from typing import List, Optional, Sequence, Tuple


LOGICAL_WIDTH, LOGICAL_HEIGHT = 480, 272
MIN_FIREFLIES, MAX_FIREFLIES, DEFAULT_FIREFLIES = 30, 260, 170
MOODS = (("NIGHT", (255, 255, 255)), ("MIST", (188, 222, 255)), ("MOSS", (195, 255, 211)))
WIND_LEVELS = (.65, 1.0, 1.45)
WIND_NAMES = ("CALM", "SOFT", "LIVELY")

SDL_INIT_VIDEO = 0x00000020
SDL_WINDOW_SHOWN = 0x00000004
SDL_WINDOW_HIDDEN = 0x00000008
SDL_WINDOW_RESIZABLE = 0x00000020
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x00001001
SDL_RENDERER_SOFTWARE = 0x00000001
SDL_RENDERER_ACCELERATED = 0x00000002
SDL_RENDERER_PRESENTVSYNC = 0x00000004
SDL_TEXTUREACCESS_STATIC = 0
SDL_PIXELFORMAT_RGBA32 = 376840196 if sys.byteorder == "little" else 373694468
SDL_BLENDMODE_NONE = 0
SDL_BLENDMODE_BLEND = 1
SDL_BLENDMODE_ADD = 2
SDL_FLIP_NONE = 0
SDL_QUIT, SDL_KEYDOWN, SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN = 0x100, 0x300, 0x400, 0x401
SDL_WINDOWEVENT = 0x200
SDL_WINDOWEVENT_LEAVE, SDL_WINDOWEVENT_FOCUS_LOST = 11, 13
SDLK_ESCAPE, SDLK_SPACE, SDLK_RETURN = 27, 32, 13
SDLK_UP, SDLK_DOWN, SDLK_LEFT, SDLK_RIGHT = 1073741906, 1073741905, 1073741904, 1073741903


class SDLRect(c.Structure):
    _fields_ = [("x", c.c_int), ("y", c.c_int), ("w", c.c_int), ("h", c.c_int)]


class SDLRendererInfo(c.Structure):
    _fields_ = [("name", c.c_char_p), ("flags", c.c_uint), ("num_texture_formats", c.c_uint),
                ("texture_formats", c.c_uint * 16), ("max_texture_width", c.c_int),
                ("max_texture_height", c.c_int)]


@dataclass
class RendererSnapshot:
    requested: str
    actual: str
    name: str
    flags: int
    video_driver: str
    window_size: Tuple[int, int]
    output_size: Tuple[int, int]
    max_texture_size: Tuple[int, int]
    hardware_error: Optional[str] = None
    gl_renderer: Optional[str] = None

    @property
    def accelerated(self) -> bool:
        return bool(self.flags & SDL_RENDERER_ACCELERATED) and not bool(self.flags & SDL_RENDERER_SOFTWARE)

    @property
    def software(self) -> bool:
        return bool(self.flags & SDL_RENDERER_SOFTWARE) and not bool(self.flags & SDL_RENDERER_ACCELERATED)

    @property
    def vsync(self) -> bool:
        return bool(self.flags & SDL_RENDERER_PRESENTVSYNC)


def _bind(lib, name, result, *arguments):
    function = getattr(lib, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


class SDL:
    """Minimal, explicit ctypes binding so the package has no pip dependency."""

    def __init__(self):
        candidates = (find_library("SDL2"), find_library("SDL2-2.0"),
                      "libSDL2-2.0.so.0", "libSDL2.so",
                      "/opt/homebrew/lib/libSDL2.dylib", "/usr/local/lib/libSDL2.dylib")
        error = None
        self.lib = None
        for library in candidates:
            if not library:
                continue
            try:
                self.lib = c.CDLL(library)
                break
            except OSError as failure:
                error = failure
        if self.lib is None:
            message = "SDL2 2.0+ is required; install the system SDL2 package."
            if error:
                message += " " + str(error)
            raise RuntimeError(message)
        ptr, integer, uint, u8, text = c.c_void_p, c.c_int, c.c_uint, c.c_ubyte, c.c_char_p
        self.Init = _bind(self.lib, "SDL_Init", integer, uint)
        self.Quit = _bind(self.lib, "SDL_Quit", None)
        self.Error = _bind(self.lib, "SDL_GetError", text)
        self.CreateWindow = _bind(self.lib, "SDL_CreateWindow", ptr, text, integer, integer, integer, integer, uint)
        self.DestroyWindow = _bind(self.lib, "SDL_DestroyWindow", None, ptr)
        self.SetWindowFullscreen = _bind(self.lib, "SDL_SetWindowFullscreen", integer, ptr, uint)
        self.GetWindowSize = _bind(self.lib, "SDL_GetWindowSize", None, ptr, c.POINTER(integer), c.POINTER(integer))
        self.ShowWindow = _bind(self.lib, "SDL_ShowWindow", None, ptr)
        self.CreateRenderer = _bind(self.lib, "SDL_CreateRenderer", ptr, ptr, integer, uint)
        self.DestroyRenderer = _bind(self.lib, "SDL_DestroyRenderer", None, ptr)
        self.GetRendererInfo = _bind(self.lib, "SDL_GetRendererInfo", integer, ptr, c.POINTER(SDLRendererInfo))
        self.GetNumRenderDrivers = _bind(self.lib, "SDL_GetNumRenderDrivers", integer)
        self.GetRenderDriverInfo = _bind(self.lib, "SDL_GetRenderDriverInfo", integer, integer, c.POINTER(SDLRendererInfo))
        self.GetRendererOutputSize = _bind(self.lib, "SDL_GetRendererOutputSize", integer, ptr, c.POINTER(integer), c.POINTER(integer))
        self.GetCurrentVideoDriver = _bind(self.lib, "SDL_GetCurrentVideoDriver", text)
        self.SetHint = _bind(self.lib, "SDL_SetHint", integer, text, text)
        self.SetRenderDrawColor = _bind(self.lib, "SDL_SetRenderDrawColor", integer, ptr, u8, u8, u8, u8)
        self.SetRenderDrawBlendMode = _bind(self.lib, "SDL_SetRenderDrawBlendMode", integer, ptr, integer)
        self.RenderClear = _bind(self.lib, "SDL_RenderClear", integer, ptr)
        self.RenderPresent = _bind(self.lib, "SDL_RenderPresent", None, ptr)
        self.RenderFillRect = _bind(self.lib, "SDL_RenderFillRect", integer, ptr, c.POINTER(SDLRect))
        self.RenderFillRects = _bind(self.lib, "SDL_RenderFillRects", integer, ptr, c.POINTER(SDLRect), integer)
        self.RenderCopy = _bind(self.lib, "SDL_RenderCopy", integer, ptr, ptr, c.POINTER(SDLRect), c.POINTER(SDLRect))
        self.RenderCopyEx = _bind(self.lib, "SDL_RenderCopyEx", integer, ptr, ptr, c.POINTER(SDLRect), c.POINTER(SDLRect), c.c_double, c.c_void_p, integer)
        self.CreateTexture = _bind(self.lib, "SDL_CreateTexture", ptr, ptr, uint, integer, integer, integer)
        self.DestroyTexture = _bind(self.lib, "SDL_DestroyTexture", None, ptr)
        self.UpdateTexture = _bind(self.lib, "SDL_UpdateTexture", integer, ptr, c.POINTER(SDLRect), c.c_void_p, integer)
        self.SetTextureBlendMode = _bind(self.lib, "SDL_SetTextureBlendMode", integer, ptr, integer)
        self.SetTextureAlphaMod = _bind(self.lib, "SDL_SetTextureAlphaMod", integer, ptr, u8)
        self.SetTextureColorMod = _bind(self.lib, "SDL_SetTextureColorMod", integer, ptr, u8, u8, u8)
        self.RenderSetLogicalSize = _bind(self.lib, "SDL_RenderSetLogicalSize", integer, ptr, integer, integer)
        self.WaitEventTimeout = _bind(self.lib, "SDL_WaitEventTimeout", integer, c.c_void_p, integer)
        self.PollEvent = _bind(self.lib, "SDL_PollEvent", integer, c.c_void_p)
        self.GetMouseState = _bind(self.lib, "SDL_GetMouseState", uint, c.POINTER(integer), c.POINTER(integer))
        self.RenderReadPixels = _bind(self.lib, "SDL_RenderReadPixels", integer, ptr, c.POINTER(SDLRect), uint, ptr, integer)
        self.GLGetCurrentContext = _bind(self.lib, "SDL_GL_GetCurrentContext", ptr)
        self.GLGetCurrentWindow = _bind(self.lib, "SDL_GL_GetCurrentWindow", ptr)
        self.GLGetProcAddress = _bind(self.lib, "SDL_GL_GetProcAddress", ptr, text)
        self.Delay = _bind(self.lib, "SDL_Delay", None, uint)

    def error(self) -> str:
        return (self.Error() or b"SDL error").decode("utf-8", "replace")


def valid_renderer(mode: str, info: SDLRendererInfo) -> bool:
    """Use the same mutually-exclusive flag checks as Vitrallis Shell."""
    accelerated = bool(info.flags & SDL_RENDERER_ACCELERATED)
    software = bool(info.flags & SDL_RENDERER_SOFTWARE)
    return (mode == "hardware" and accelerated and not software) or (mode == "software" and software and not accelerated)


def renderer_drivers(sdl: SDL) -> List[Tuple[int, SDLRendererInfo]]:
    drivers = []
    for index in range(max(0, sdl.GetNumRenderDrivers())):
        info = SDLRendererInfo()
        if sdl.GetRenderDriverInfo(index, c.byref(info)) == 0:
            drivers.append((index, info))
    return drivers


def parse_renderer(value: str) -> str:
    if value in ("auto", "hardware", "software"):
        return value
    raise ValueError("invalid renderer %r; use auto, hardware or software" % value)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    ratio = clamp((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return ratio * ratio * (3.0 - 2.0 * ratio)


def hash01(x: int, y: int = 0) -> float:
    value = (x * 374761393 + y * 668265263) & 0xffffffff
    value = (value ^ (value >> 13)) * 1274126177 & 0xffffffff
    return ((value ^ (value >> 16)) & 0xffff) / 65535.0


def load_artwork(name: str, width: int, height: int) -> Tuple[int, int, bytearray]:
    """Decode a bounded packaged RGBA texture without an image-library dependency."""
    path = Path(__file__).resolve().parent / "assets" / (name + ".rgba.z")
    expected = width * height * 4
    try:
        with path.open("rb") as source:
            packed = source.read(expected + 1025)
        if len(packed) > expected + 1024:
            raise ValueError("oversized texture")
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(packed, expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("invalid texture length or trailing data")
    except (OSError, ValueError, zlib.error) as error:
        raise RuntimeError("Unable to load artwork %s: %s" % (path.name, error)) from error
    return width, height, bytearray(pixels)


def software_gl_renderer(name: str) -> bool:
    """Match the current Shell's known CPU rasterizers without substring false positives."""
    lowered = name.lower()
    return bool(set(re.findall(r"[a-z0-9]+", lowered)) & {"llvmpipe", "softpipe", "swrast", "swr"}) or "software rasterizer" in lowered


@dataclass
class Firefly:
    x: float
    y: float
    vx: float
    vy: float
    direction: float
    depth: float
    size: float
    phase: float
    blink_rate: float
    turn_at: float
    hover: float
    group: int


class Field:
    def __init__(self, count: int = DEFAULT_FIREFLIES, seed: int = 1203) -> None:
        self.random = random.Random(seed)
        self.fireflies: List[Firefly] = []
        self.time = 0.0
        self.movement = 1.0
        self.glow = .8
        self.paused = False
        self.pointer: Optional[Tuple[float, float]] = None
        self.shooting_star = 9.0
        self.reseed(count)

    def new_firefly(self) -> Firefly:
        depth = self.random.uniform(.25, 1.0)
        direction = self.random.uniform(-math.pi, math.pi)
        speed = self.random.uniform(4.5, 13.0) * (.45 + depth)
        return Firefly(self.random.uniform(-12, LOGICAL_WIDTH + 12), self.random.uniform(88, 252),
                        math.cos(direction) * speed, math.sin(direction) * speed * .55, direction, depth,
                        .45 + depth * 1.25, self.random.uniform(0, math.tau), self.random.uniform(.65, 1.45),
                        self.random.uniform(.2, 2.7), self.random.uniform(.1, 1.5), self.random.randrange(5))

    def reseed(self, count: Optional[int] = None) -> None:
        target = len(self.fireflies) if count is None else int(clamp(count, MIN_FIREFLIES, MAX_FIREFLIES))
        self.fireflies = [self.new_firefly() for _ in range(target)]
        self.time = 0.0
        self.shooting_star = 9.0
        self.fireflies.sort(key=lambda fly: fly.depth)

    def change_population(self, amount: int) -> None:
        target = int(clamp(len(self.fireflies) + amount, MIN_FIREFLIES, MAX_FIREFLIES))
        if target < len(self.fireflies):
            del self.fireflies[target:]
        else:
            self.fireflies.extend(self.new_firefly() for _ in range(target - len(self.fireflies)))
            self.fireflies.sort(key=lambda fly: fly.depth)

    def pulse(self, x: float, y: float) -> None:
        """A click is a gentle local scatter, never a game-like explosion."""
        for fly in self.fireflies:
            dx, dy = fly.x - x, fly.y - y
            distance = math.hypot(dx, dy)
            if 1 < distance < 90:
                strength = (1 - distance / 90) * 22 * (.4 + fly.depth)
                fly.vx += dx / distance * strength
                fly.vy += dy / distance * strength

    def brightness(self, fly: Firefly) -> float:
        group_wave = math.sin(self.time * .72 + fly.group * .9)
        individual = math.sin(self.time * fly.blink_rate * math.tau + fly.phase)
        pulse = smoothstep(-.25, .7, individual) * .72 + .28
        loose_sync = .82 + max(0.0, group_wave) * .18
        return clamp(pulse * loose_sync * (.35 + fly.depth * .65), 0.0, 1.0)

    def update(self, dt: float) -> None:
        if self.paused:
            return
        dt = min(dt, .05)
        self.time += dt
        self.shooting_star -= dt
        if self.shooting_star < 0:
            self.shooting_star = self.random.uniform(14, 30)
        for fly in self.fireflies:
            fly.turn_at -= dt
            if fly.turn_at <= 0:
                fly.turn_at = self.random.uniform(.45, 2.4)
                fly.direction += self.random.uniform(-.85, .85)
                fly.hover = self.random.uniform(.15, .75)
            fly.hover -= dt
            wander = math.sin(self.time * (1.4 + fly.depth) + fly.phase) * .30
            target_speed = (2.0 if fly.hover > 0 else 7.5 + fly.depth * 11) * self.movement
            target_x = math.cos(fly.direction + wander) * target_speed
            target_y = math.sin(fly.direction * 1.6 + wander) * target_speed * .55
            if self.pointer:
                dx, dy = fly.x - self.pointer[0], fly.y - self.pointer[1]
                distance = math.hypot(dx, dy)
                if 1 < distance < 54:
                    repel = (1 - distance / 54) * (30 + fly.depth * 24)
                    target_x += dx / distance * repel
                    target_y += dy / distance * repel
            easing = min(1.0, dt * 2.7)
            fly.vx += (target_x - fly.vx) * easing
            fly.vy += (target_y - fly.vy) * easing
            fly.x += fly.vx * dt
            fly.y += fly.vy * dt
            if fly.x < -18: fly.x = LOGICAL_WIDTH + 15
            if fly.x > LOGICAL_WIDTH + 18: fly.x = -15
            if fly.y < 75: fly.y, fly.vy = 76, abs(fly.vy)
            if fly.y > 260: fly.y, fly.vy = 259, -abs(fly.vy)


@dataclass(frozen=True)
class PerformanceReading:
    """A deliberately narrow, local performance snapshot."""
    cpu_percent: Optional[float]
    gpu_percent: Optional[float]


class PerformanceMeter:
    """Sample portable CPU and exposed DRM busy counters without subprocesses.

    GPU utilisation has no portable SDL metric. A missing `gpu_busy_percent`
    counter is reported as unavailable instead of guessing from frame rate,
    renderer flags or clock frequency.
    """
    def __init__(self, proc_root: Path = Path("/proc"), sys_root: Path = Path("/sys")) -> None:
        self.proc_root, self.sys_root = proc_root, sys_root
        self.cpu_previous: Optional[Tuple[int, int]] = None
        self.gpu_paths: List[Path] = []
        self.next_sample, self.next_discovery = 0.0, 0.0
        self.reading = PerformanceReading(None, None)

    @staticmethod
    def read(path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="ascii", errors="replace")
        except OSError:
            return None

    @staticmethod
    def cpu_totals(raw: Optional[str]) -> Optional[Tuple[int, int]]:
        if not raw:
            return None
        for line in raw.splitlines():
            parts = line.split()
            if not parts or parts[0] != "cpu":
                continue
            try:
                values = [int(value) for value in parts[1:]]
            except ValueError:
                return None
            if len(values) < 4 or any(value < 0 for value in values):
                return None
            # Linux guest and guest_nice are already included in user and nice.
            return sum(values[:8]), values[3] + (values[4] if len(values) > 4 else 0)
        return None

    def discover_gpu_paths(self, now: float) -> None:
        if now < self.next_discovery:
            return
        self.gpu_paths = []
        try:
            cards = sorted((self.sys_root / "class/drm").glob("card[0-9]*"))
            for card in cards:
                if card.name[4:].isdigit():
                    counter = card / "device/gpu_busy_percent"
                    if counter.is_file():
                        self.gpu_paths.append(counter)
        except OSError:
            pass
        self.next_discovery = now + 30.0

    def sample(self, now: float) -> PerformanceReading:
        if now < self.next_sample:
            return self.reading
        self.next_sample = now + .75
        totals = self.cpu_totals(self.read(self.proc_root / "stat"))
        cpu = None
        if totals:
            if self.cpu_previous:
                total_delta, idle_delta = totals[0] - self.cpu_previous[0], totals[1] - self.cpu_previous[1]
                if total_delta > 0 and 0 <= idle_delta <= total_delta:
                    cpu = (total_delta - idle_delta) * 100.0 / total_delta
            self.cpu_previous = totals
        self.discover_gpu_paths(now)
        gpu = None
        # SDL2 does not expose a portable mapping to DRM cards. Avoid choosing
        # an arbitrary GPU on multi-adapter hosts. The UI labels this DRM load.
        for path in self.gpu_paths if len(self.gpu_paths) == 1 else ():
            raw = self.read(path)
            try:
                value = float(raw.strip()) if raw is not None else -1.0
            except ValueError:
                continue
            if 0.0 <= value <= 100.0:
                gpu = value
                break
        self.reading = PerformanceReading(cpu, gpu)
        return self.reading


FONT = {
    "B": (30, 17, 17, 30, 17, 17, 30), "J": (7, 2, 2, 2, 18, 18, 12),
    "K": (17, 18, 20, 24, 20, 18, 17), "Q": (14, 17, 17, 17, 21, 18, 13),
    "Z": (31, 1, 2, 4, 8, 16, 31),
    " ": (0, 0, 0, 0, 0, 0, 0), "A": (14, 17, 17, 31, 17, 17, 17), "C": (15, 16, 16, 16, 16, 16, 15),
    "D": (30, 17, 17, 17, 17, 17, 30), "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (15, 16, 16, 23, 17, 17, 15), "H": (17, 17, 17, 31, 17, 17, 17), "I": (31, 4, 4, 4, 4, 4, 31),
    "L": (16, 16, 16, 16, 16, 16, 31), "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14), "P": (30, 17, 17, 30, 16, 16, 16), "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "T": (31, 4, 4, 4, 4, 4, 4), "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4), "W": (17, 17, 17, 21, 21, 21, 10), "X": (17, 17, 10, 4, 10, 17, 17), "Y": (17, 17, 10, 4, 4, 4, 4),
    "0": (14, 17, 19, 21, 25, 17, 14), "1": (4, 12, 4, 4, 4, 4, 14), "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (30, 1, 1, 14, 1, 1, 30), "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14), "7": (31, 1, 2, 4, 8, 8, 8), "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 1, 14), ":": (0, 4, 0, 0, 4, 0, 0), "-": (0, 0, 0, 31, 0, 0, 0), "%": (17, 2, 4, 8, 16, 0, 17),
}


def text_pixels(text: str, scale: int, color):
    """Rasterize the existing pixel font once, preserving exact glyph geometry."""
    if not 1 <= scale <= 4 or len(text) > 80:
        raise ValueError("Text texture exceeds label budget")
    width, height = max(1, len(text) * 6 * scale), 7 * scale
    pixels = bytearray(width * height * 4)
    ink = bytes(color)
    for index, char in enumerate(text.upper()):
        for row, bits in enumerate(FONT.get(char, FONT[" "])):
            for column in range(5):
                if bits & (1 << (4 - column)):
                    for dy in range(scale):
                        offset = ((row * scale + dy) * width + (index * 6 + column) * scale) * 4
                        pixels[offset:offset + scale * 4] = ink * scale
    return width, height, pixels


class FireflyApp:
    def __init__(self, sdl: SDL, fullscreen: bool = True, renderer: str = "auto") -> None:
        self.sdl, self.window, self.renderer = sdl, None, None
        self.textures: List[c.c_void_p] = []
        self.text_cache = {}
        self.sprite_batch = None
        self.field = Field()
        self.show_status = True
        self.show_performance = False
        self.performance = PerformanceMeter()
        self.mood_index = 0
        self.wind_index = 1
        self.running = True
        self.fps, self.frames, self.fps_then = 0, 0, time.monotonic()
        self.renderer_name, self.accelerated = "Unknown", False
        self.renderer_snapshot: Optional[RendererSnapshot] = None
        self.fullscreen = fullscreen
        self.requested_renderer = parse_renderer(renderer)
        if sdl.Init(SDL_INIT_VIDEO) != 0:
            raise RuntimeError("SDL video startup failed: " + sdl.error())
        try:
            # Keep an unsuccessful hidden renderer from posting a synthetic quit.
            sdl.SetHint(b"SDL_QUIT_ON_LAST_WINDOW_CLOSE", b"0")
            sdl.SetHint(b"SDL_VIDEO_ALLOW_SCREENSAVER", b"1")
            sdl.SetHint(b"SDL_TOUCH_MOUSE_EVENTS", b"1")
            sdl.SetHint(b"SDL_MOUSE_TOUCH_EVENTS", b"0")
            self.window, self.renderer, self.renderer_snapshot = self.select_renderer()
            self.renderer_name = self.renderer_snapshot.name
            self.accelerated = self.renderer_snapshot.accelerated
            if sdl.RenderSetLogicalSize(self.renderer, LOGICAL_WIDTH, LOGICAL_HEIGHT) != 0:
                raise RuntimeError("SDL logical size failed: " + sdl.error())
            self.scene = self.texture(*load_artwork("meadow", 480, 272), SDL_BLENDMODE_NONE)
            self.glow_texture = self.texture(*load_artwork("glow", 64, 64), SDL_BLENDMODE_ADD)
            self.fly_texture = self.texture(*load_artwork("firefly", 20, 14), SDL_BLENDMODE_BLEND)
            self.grass_texture = self.texture(*load_artwork("grass", 18, 42), SDL_BLENDMODE_BLEND)
            if self.accelerated:
                try:
                    self.sprite_batch = SpriteBatch(self, load_artwork, MAX_FIREFLIES * 2 + 24)
                except RuntimeError as error:
                    print("event=sprite_batch mode=individual reason=%r" % str(error), file=sys.stderr)
        except BaseException:
            self.close()
            raise

    def make_window(self):
        flags = SDL_WINDOW_HIDDEN | SDL_WINDOW_RESIZABLE
        if self.fullscreen:
            flags |= SDL_WINDOW_FULLSCREEN_DESKTOP
        window = self.sdl.CreateWindow(b"Firefly Field", c.c_int(80), c.c_int(80), LOGICAL_WIDTH, LOGICAL_HEIGHT, flags)
        if not window:
            raise RuntimeError("SDL window creation failed: " + self.sdl.error())
        return window

    def attempt_renderer(self, index: int, mode: str, vsync: bool):
        """Try one driver with one fresh hidden window, mirroring Shell policy."""
        window = self.make_window()
        flags = SDL_RENDERER_SOFTWARE if mode == "software" else SDL_RENDERER_ACCELERATED
        if vsync:
            flags |= SDL_RENDERER_PRESENTVSYNC
        renderer = self.sdl.CreateRenderer(window, index, flags)
        if not renderer:
            detail = self.sdl.error()
            self.sdl.DestroyWindow(window)
            raise RuntimeError(detail)
        info = SDLRendererInfo()
        status = self.sdl.GetRendererInfo(renderer, c.byref(info))
        if status != 0 or not valid_renderer(mode, info):
            detail = self.sdl.error() if status != 0 else "renderer flags=%#x do not satisfy %s mode" % (info.flags, mode)
            self.sdl.DestroyRenderer(renderer)
            self.sdl.DestroyWindow(window)
            raise RuntimeError(detail)
        self.active_gl_renderer = self.current_gl_renderer(window, renderer, info)
        if mode == "hardware" and self.active_gl_renderer and software_gl_renderer(self.active_gl_renderer):
            self.sdl.DestroyRenderer(renderer)
            self.sdl.DestroyWindow(window)
            raise RuntimeError("SDL accelerated backend uses CPU rasterizer %r" % self.active_gl_renderer)
        # Show only a verified renderer. Fullscreen output size may settle here.
        self.sdl.ShowWindow(window)
        width, height = c.c_int(), c.c_int()
        if self.sdl.GetRendererOutputSize(renderer, c.byref(width), c.byref(height)) != 0:
            self.sdl.DestroyRenderer(renderer)
            self.sdl.DestroyWindow(window)
            raise RuntimeError(self.sdl.error())
        return window, renderer, info, (width.value, height.value)

    def current_gl_renderer(self, window, renderer, info: SDLRendererInfo) -> Optional[str]:
        if info.name not in (b"opengl", b"opengles", b"opengles2"):
            return None
        pixel = (c.c_ubyte * 4)()
        rect = SDLRect(0, 0, 1, 1)
        # One startup readback activates this SDL backend; never read back a frame.
        if self.sdl.RenderReadPixels(renderer, c.byref(rect), SDL_PIXELFORMAT_RGBA32, pixel, 4) != 0:
            return None
        if not self.sdl.GLGetCurrentContext() or self.sdl.GLGetCurrentWindow() != window:
            return None
        address = self.sdl.GLGetProcAddress(b"glGetString")
        if not address:
            return None
        query = c.CFUNCTYPE(c.c_char_p, c.c_uint)(address)
        value = query(0x1F01)  # GL_RENDERER, copied before the context can be destroyed.
        return value.decode("utf-8", "replace") if value else None

    def snapshot(self, actual: str, info: SDLRendererInfo, output: Tuple[int, int], hardware_error: Optional[str]) -> RendererSnapshot:
        width, height = c.c_int(), c.c_int()
        self.sdl.GetWindowSize(self.window, c.byref(width), c.byref(height))
        driver = (self.sdl.GetCurrentVideoDriver() or b"unknown").decode("utf-8", "replace")
        return RendererSnapshot(self.requested_renderer, actual, (info.name or b"SDL").decode("utf-8", "replace"),
                                info.flags, driver, (width.value, height.value), output,
                                (info.max_texture_width, info.max_texture_height), hardware_error, self.active_gl_renderer)

    def select_renderer(self):
        drivers = renderer_drivers(self.sdl)
        failures: List[str] = []
        if self.requested_renderer != "software":
            hardware = [(index, info) for index, info in drivers if valid_renderer("hardware", info)]
            # Vitrallis Shell's GLES2 compatibility floor is preferred when SDL advertises it.
            hardware.sort(key=lambda item: (item[1].name or b"").decode("utf-8", "replace") != "opengles2")
            for vsync in (True, False):
                for index, advertised in hardware:
                    name = (advertised.name or b"unknown").decode("utf-8", "replace")
                    try:
                        window, renderer, info, output = self.attempt_renderer(index, "hardware", vsync)
                        self.window = window
                        return window, renderer, self.snapshot("hardware", info, output, None)
                    except RuntimeError as error:
                        failures.append("driver=%r vsync=%s: %s" % (name, str(vsync).lower(), error))
            if not failures:
                failures.append("SDL advertises no accelerated render drivers")
        hardware_error = "; ".join(failures) if failures else None
        if self.requested_renderer == "hardware":
            raise RuntimeError("hardware renderer unavailable: %s; check SDL/Mesa drivers and display access, or use --renderer auto or --renderer software" % (hardware_error or "no accelerated renderer"))
        for index, advertised in drivers:
            if not valid_renderer("software", advertised):
                continue
            try:
                window, renderer, info, output = self.attempt_renderer(index, "software", False)
                self.window = window
                return window, renderer, self.snapshot("software", info, output, hardware_error)
            except RuntimeError as error:
                raise RuntimeError("software renderer unavailable: %s; hardware attempt: %s" % (error, hardware_error or "not requested")) from error
        raise RuntimeError("software renderer unavailable: SDL advertises no software render driver; hardware attempt: %s" % (hardware_error or "not requested"))

    def log_renderer(self) -> None:
        snapshot = self.renderer_snapshot
        if not snapshot:
            return
        message = ("level=info event=renderer_initialized requested=%s mode=%s driver=%r accelerated=%s software=%s vsync=%s "
                   "max_texture_width=%d max_texture_height=%d video_driver=%r window_width=%d window_height=%d output_width=%d output_height=%d fallback=%s" %
                   (snapshot.requested, snapshot.actual, snapshot.name, str(snapshot.accelerated).lower(), str(snapshot.software).lower(),
                    str(snapshot.vsync).lower(), snapshot.max_texture_size[0], snapshot.max_texture_size[1], snapshot.video_driver,
                    snapshot.window_size[0], snapshot.window_size[1], snapshot.output_size[0], snapshot.output_size[1],
                    str(bool(snapshot.hardware_error)).lower()))
        message += " flags=%#x gl_renderer=%r" % (snapshot.flags, snapshot.gl_renderer)
        if snapshot.hardware_error:
            message += " hardware_error=%r" % snapshot.hardware_error
        print(message + " app='Firefly Field'", file=sys.stderr)

    def texture(self, width: int, height: int, pixels: bytearray, blend: int):
        texture = self.sdl.CreateTexture(self.renderer, SDL_PIXELFORMAT_RGBA32, SDL_TEXTUREACCESS_STATIC, width, height)
        if not texture:
            raise RuntimeError("SDL texture creation failed: " + self.sdl.error())
        buffer = (c.c_ubyte * len(pixels)).from_buffer(pixels)
        if self.sdl.UpdateTexture(texture, None, buffer, width * 4) != 0:
            self.sdl.DestroyTexture(texture)
            raise RuntimeError("SDL texture upload failed: " + self.sdl.error())
        if self.sdl.SetTextureBlendMode(texture, blend) != 0:
            self.sdl.DestroyTexture(texture)
            raise RuntimeError("SDL texture blend mode failed: " + self.sdl.error())
        self.textures.append(texture)
        return texture

    def copy(self, texture, x: float, y: float, width: float, height: float, alpha: int = 255, angle: float = 0) -> None:
        if self.sprite_batch is not None:
            name = "glow" if texture == self.glow_texture else "firefly" if texture == self.fly_texture else "grass"
            self.sprite_batch.add(name, x, y, width, height, alpha, angle)
            return
        self.sdl.SetTextureAlphaMod(texture, int(clamp(alpha, 0, 255)))
        destination = SDLRect(int(x - width / 2), int(y - height / 2), max(1, int(width)), max(1, int(height)))
        self.sdl.RenderCopyEx(self.renderer, texture, None, c.byref(destination), angle, None, SDL_FLIP_NONE)

    def draw_text(self, x: int, y: int, text: str, scale: int = 1, color=(209, 239, 183, 255)) -> None:
        # Cache by label position, replacing a texture only when its text changes.
        # This bounds resource count and removes thousands of per-frame glyph
        # rectangles and their Python/ctypes allocations from the menu path.
        slot = (x, y)
        key = (text, scale, color)
        cached = self.text_cache.get(slot)
        if cached is None or cached[0] != key:
            width, height, pixels = text_pixels(text, scale, color)
            texture = self.texture(width, height, pixels, SDL_BLENDMODE_BLEND)
            if cached is not None:
                self.sdl.DestroyTexture(cached[1])
                self.textures.remove(cached[1])
            cached = (key, texture, width, height)
            self.text_cache[slot] = cached
        destination = SDLRect(x, y, cached[2], cached[3])
        self.sdl.RenderCopy(self.renderer, cached[1], None, c.byref(destination))

    def draw_status(self) -> None:
        # H exposes the complete keyboard path without cluttering the resting scene.
        panel = SDLRect(10, 10, 178, 214)
        self.sdl.SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_BLEND)
        self.sdl.SetRenderDrawColor(self.renderer, 4, 14, 18, 215)
        self.sdl.RenderFillRect(self.renderer, c.byref(panel))
        self.sdl.SetRenderDrawColor(self.renderer, 126, 193, 163, 105)
        for edge in (SDLRect(10, 10, 178, 1), SDLRect(10, 223, 178, 1),
                     SDLRect(10, 10, 1, 214), SDLRect(187, 10, 1, 214)):
            self.sdl.RenderFillRect(self.renderer, c.byref(edge))
        self.sdl.SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_NONE)
        self.draw_text(17, 16, "FIREFLY FIELD", 1)
        self.draw_text(17, 29, "FIREFLIES: %03d" % len(self.field.fireflies), 1, (170, 205, 167, 255))
        self.draw_text(17, 40, "FPS: %02d" % self.fps, 1, (170, 205, 167, 255))
        name = ("GPU " if self.accelerated else "SDL ") + self.renderer_name[:10]
        self.draw_text(17, 51, name, 1, (170, 205, 167, 255))
        self.draw_text(17, 62, "STATE: " + ("PAUSED" if self.field.paused else "FLOW"), 1)
        self.draw_text(17, 73, "MOOD: " + MOODS[self.mood_index][0], 1)
        self.draw_text(17, 84, "WIND: " + WIND_NAMES[self.wind_index], 1)
        self.draw_text(17, 99, "SPACE: PAUSE", 1)
        self.draw_text(17, 110, "R: RESEED", 1)
        self.draw_text(17, 121, "UP DOWN: TEN", 1)
        self.draw_text(17, 132, "A D: ONE", 1)
        self.draw_text(17, 143, "LEFT RIGHT: GLOW", 1)
        self.draw_text(17, 154, "P: STATS", 1)
        self.draw_text(17, 165, "C: MOOD", 1)
        self.draw_text(17, 176, "W: WIND", 1)
        self.draw_text(17, 187, "ESC: EXIT", 1)
        self.draw_text(17, 198, "ENTER: SCATTER", 1)
        self.draw_text(17, 209, "H: HIDE", 1, (170, 205, 167, 255))

    @staticmethod
    def percentage(value: Optional[float]) -> str:
        return "---" if value is None else "%03d%%" % round(clamp(value, 0.0, 100.0))

    def draw_performance(self, now: float) -> None:
        """A compact opt-in overlay, kept off by default for a quiet scene."""
        reading = self.performance.sample(now)
        panel = SDLRect(399, 10, 71, 37)
        self.sdl.SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_BLEND)
        self.sdl.SetRenderDrawColor(self.renderer, 4, 14, 18, 205)
        self.sdl.RenderFillRect(self.renderer, c.byref(panel))
        self.sdl.SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_NONE)
        self.draw_text(405, 16, "CPU:" + self.percentage(reading.cpu_percent), 1, (170, 205, 167, 255))
        self.draw_text(405, 29, "DRM:" + self.percentage(reading.gpu_percent), 1, (170, 205, 167, 255))

    def draw_twinkles(self) -> None:
        """A small deterministic star pass adds life without texture uploads."""
        for index in range(24):
            x = int(12 + hash01(index, 101) * (LOGICAL_WIDTH - 24))
            y = int(14 + hash01(index, 103) * 126)
            pulse = .52 + .48 * math.sin(self.field.time * (.58 + hash01(index, 107)) + index)
            brightness = int(58 + 104 * pulse)
            self.sdl.SetRenderDrawColor(self.renderer, brightness // 2, brightness // 2, brightness, 255)
            size = 2 if pulse > .94 and index % 5 == 0 else 1
            star = SDLRect(x, y, size, size)
            self.sdl.RenderFillRect(self.renderer, c.byref(star))

    def draw_shooting_star(self) -> None:
        if not 0 < self.field.shooting_star < .75:
            return
        progress = 1 - self.field.shooting_star / .75
        # Draw the tail first so the small bright head remains crisp.
        for segment in range(4, -1, -1):
            tail = max(0.0, progress - segment * .055)
            alpha = int(150 * (1 - progress) * (1 - segment * .15))
            size = 8 + (4 - segment) * 2
            self.copy(self.glow_texture, 70 + tail * 190, 45 + tail * 60, size, size, alpha)

    def render(self) -> None:
        self.sdl.SetRenderDrawColor(self.renderer, 3, 10, 20, 255)
        self.sdl.RenderClear(self.renderer)
        _, tint = MOODS[self.mood_index]
        self.sdl.SetTextureColorMod(self.scene, *tint)
        destination = SDLRect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT)
        self.sdl.RenderCopy(self.renderer, self.scene, None, c.byref(destination))
        self.draw_twinkles()
        # Far insects are first, selling depth while leaving close sprites readable.
        for fly in self.field.fireflies:
            brightness = self.field.brightness(fly)
            glow_size = (15 + fly.depth * 31) * fly.size * (0.65 + brightness * .7) * self.field.glow
            self.copy(self.glow_texture, fly.x, fly.y, glow_size, glow_size, int(255 * brightness * self.field.glow))
            body_size = (6 + fly.depth * 9) * fly.size
            heading = math.degrees(math.atan2(fly.vy, fly.vx)) + 90
            self.copy(self.fly_texture, fly.x, fly.y, body_size * 1.35, body_size, int(80 + 175 * brightness), heading)
        # A handful of cheap texture copies gives the foreground a living edge.
        for index in range(19):
            x = index * 28 - 10
            sway = math.sin(self.field.time * .75 + index * .91) * (2 + index % 3) * WIND_LEVELS[self.wind_index]
            self.copy(self.grass_texture, x, 257, 20, 46, 180, sway)
        self.draw_shooting_star()
        if self.sprite_batch is not None:
            self.sprite_batch.present()
        if self.show_status:
            self.draw_status()
        if self.show_performance:
            self.draw_performance(time.monotonic())
        self.sdl.RenderPresent(self.renderer)

    def handle_key(self, sym: int) -> None:
        """Every ambient control has a direct keyboard equivalent."""
        if sym == SDLK_ESCAPE: self.running = False
        elif sym == SDLK_SPACE: self.field.paused = not self.field.paused
        elif sym in (ord("r"), ord("R")): self.field.reseed(len(self.field.fireflies))
        elif sym in (ord("h"), ord("H")): self.show_status = not self.show_status
        elif sym in (ord("p"), ord("P")): self.show_performance = not self.show_performance
        elif sym in (ord("a"), ord("A")): self.field.change_population(1)
        elif sym in (ord("d"), ord("D")): self.field.change_population(-1)
        elif sym in (ord("c"), ord("C")): self.mood_index = (self.mood_index + 1) % len(MOODS)
        elif sym in (ord("w"), ord("W")): self.wind_index = (self.wind_index + 1) % len(WIND_LEVELS)
        elif sym == SDLK_RETURN: self.field.pulse(LOGICAL_WIDTH / 2, LOGICAL_HEIGHT / 2)
        elif sym == SDLK_UP: self.field.change_population(10)
        elif sym == SDLK_DOWN: self.field.change_population(-10)
        elif sym == SDLK_LEFT: self.field.glow = clamp(self.field.glow - .1, .2, 1.4)
        elif sym == SDLK_RIGHT: self.field.glow = clamp(self.field.glow + .1, .2, 1.4)

    def events(self, wait_ms=0) -> bool:
        event = (c.c_ubyte * 56)()
        ready = self.sdl.WaitEventTimeout(c.byref(event), wait_ms) if wait_ms else self.sdl.PollEvent(c.byref(event))
        changed = bool(ready)
        while ready:
            kind = c.c_uint32.from_buffer(event, 0).value
            if kind == SDL_QUIT:
                self.running = False
            elif kind == SDL_WINDOWEVENT and event[12] in (SDL_WINDOWEVENT_LEAVE, SDL_WINDOWEVENT_FOCUS_LOST):
                self.field.pointer = None
            elif kind == SDL_KEYDOWN and not event[13]:
                self.handle_key(c.c_int32.from_buffer(event, 20).value)
            elif kind == SDL_MOUSEMOTION:
                self.field.pointer = (float(c.c_int32.from_buffer(event, 20).value), float(c.c_int32.from_buffer(event, 24).value))
            elif kind == SDL_MOUSEBUTTONDOWN:
                x, y = c.c_int32.from_buffer(event, 16).value, c.c_int32.from_buffer(event, 20).value
                self.field.pulse(float(x), float(y))
            ready = self.sdl.PollEvent(c.byref(event))
        return changed

    def run(self) -> None:
        previous = time.monotonic()
        redraw = True
        while self.running:
            # A paused scene waits on native events. Live counters refresh at
            # one second; unchanged pixels do not generate GPU work.
            paused = self.field.paused
            changed = self.events(1000 if paused and not redraw else 0)
            now = time.monotonic()
            self.field.update(now - previous)
            previous = now
            if now - self.fps_then >= 1:
                self.fps, self.frames, self.fps_then = self.frames, 0, now
                redraw = self.show_status or self.show_performance
            if not self.running:
                break
            if not self.field.paused or redraw or changed:
                self.render()
                self.frames += 1
                redraw = False
            remaining = 1.0 / 30.0 - (time.monotonic() - now)
            if not self.renderer_snapshot.vsync and not self.field.paused and remaining > 0:
                self.sdl.Delay(max(1, math.ceil(remaining * 1000)))

    def close(self) -> None:
        if self.renderer:
            for texture in self.textures:
                self.sdl.DestroyTexture(texture)
            self.textures.clear()
            self.sdl.DestroyRenderer(self.renderer)
            self.renderer = None
        if self.window:
            self.sdl.DestroyWindow(self.window)
            self.window = None
        self.sdl.Quit()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        field = Field()
        field.update(.016)
        print("Firefly Field simulation ready (%d fireflies)." % len(field.fireflies))
        return 0
    windowed, renderer = False, "auto"
    position = 0
    while position < len(args):
        argument = args[position]
        if argument == "--windowed":
            windowed = True
        elif argument == "--renderer" and position + 1 < len(args):
            position += 1
            try:
                renderer = parse_renderer(args[position])
            except ValueError as error:
                print("Firefly Field: " + str(error), file=sys.stderr)
                return 2
        elif argument == "--help":
            print("Usage: python3 main.py [--check] [--windowed] [--renderer auto|hardware|software]")
            return 0
        else:
            print("Usage: python3 main.py [--check] [--windowed] [--renderer auto|hardware|software]", file=sys.stderr)
            return 2
        position += 1
    try:
        app = FireflyApp(SDL(), fullscreen=not windowed, renderer=renderer)
        try:
            app.log_renderer()
            app.run()
        finally:
            app.close()
    except (RuntimeError, OSError) as error:
        print("Firefly Field: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
