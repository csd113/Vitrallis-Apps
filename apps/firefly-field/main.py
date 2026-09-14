#!/usr/bin/env python3
"""A calm, GPU-friendly SDL2 firefly field for small Vitrallis displays.

Artwork is created once as small RGBA textures.  The frame loop only updates
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
import sys
import time
from typing import Iterable, List, Optional, Sequence, Tuple


LOGICAL_WIDTH, LOGICAL_HEIGHT = 480, 272
MIN_FIREFLIES, MAX_FIREFLIES, DEFAULT_FIREFLIES = 30, 260, 170

SDL_INIT_VIDEO = 0x00000020
SDL_WINDOW_SHOWN = 0x00000004
SDL_WINDOW_HIDDEN = 0x00000008
SDL_WINDOW_RESIZABLE = 0x00000020
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x00001001
SDL_RENDERER_SOFTWARE = 0x00000001
SDL_RENDERER_ACCELERATED = 0x00000002
SDL_RENDERER_PRESENTVSYNC = 0x00000004
SDL_TEXTUREACCESS_STATIC = 0
SDL_PIXELFORMAT_RGBA32 = 376840196
SDL_BLENDMODE_NONE = 0
SDL_BLENDMODE_BLEND = 1
SDL_BLENDMODE_ADD = 2
SDL_FLIP_NONE = 0
SDL_QUIT, SDL_KEYDOWN, SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN = 0x100, 0x300, 0x400, 0x401


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
        self.RenderClear = _bind(self.lib, "SDL_RenderClear", integer, ptr)
        self.RenderPresent = _bind(self.lib, "SDL_RenderPresent", None, ptr)
        self.RenderFillRect = _bind(self.lib, "SDL_RenderFillRect", integer, ptr, c.POINTER(SDLRect))
        self.RenderCopy = _bind(self.lib, "SDL_RenderCopy", integer, ptr, ptr, c.POINTER(SDLRect), c.POINTER(SDLRect))
        self.RenderCopyEx = _bind(self.lib, "SDL_RenderCopyEx", integer, ptr, ptr, c.POINTER(SDLRect), c.POINTER(SDLRect), c.c_double, c.c_void_p, integer)
        self.CreateTexture = _bind(self.lib, "SDL_CreateTexture", ptr, ptr, uint, integer, integer, integer)
        self.DestroyTexture = _bind(self.lib, "SDL_DestroyTexture", None, ptr)
        self.UpdateTexture = _bind(self.lib, "SDL_UpdateTexture", integer, ptr, c.POINTER(SDLRect), c.c_void_p, integer)
        self.SetTextureBlendMode = _bind(self.lib, "SDL_SetTextureBlendMode", integer, ptr, integer)
        self.SetTextureAlphaMod = _bind(self.lib, "SDL_SetTextureAlphaMod", integer, ptr, u8)
        self.RenderSetLogicalSize = _bind(self.lib, "SDL_RenderSetLogicalSize", integer, ptr, integer, integer)
        self.PollEvent = _bind(self.lib, "SDL_PollEvent", integer, c.c_void_p)
        self.GetMouseState = _bind(self.lib, "SDL_GetMouseState", uint, c.POINTER(integer), c.POINTER(integer))
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


def rgba_texture_pixels(width: int, height: int, fill=(0, 0, 0, 0)) -> bytearray:
    return bytearray(fill * (width * height))


def set_pixel(pixels: bytearray, width: int, x: int, y: int, color: Tuple[int, int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < len(pixels) // (width * 4):
        offset = (y * width + x) * 4
        pixels[offset:offset + 4] = bytes(color)


def make_scene() -> Tuple[int, int, bytearray]:
    """Original, limited-palette scene artwork made once at launch."""
    width, height = LOGICAL_WIDTH, LOGICAL_HEIGHT
    pixels = rgba_texture_pixels(width, height)
    for y in range(height):
        sky = clamp(y / 185.0, 0.0, 1.0)
        color = (int(5 + sky * 6), int(13 + sky * 17), int(30 + sky * 15), 255)
        for x in range(width):
            set_pixel(pixels, width, x, y, color)
    for index in range(112):
        x, y = int(hash01(index, 7) * width), int(hash01(index, 13) * 145)
        brightness = 74 + int(hash01(index, 19) * 90)
        set_pixel(pixels, width, x, y, (brightness // 2, brightness // 2, brightness, 255))
    # A dim moon haze, distant hills and a tree line.
    for y in range(34, 130):
        for x in range(290, 394):
            distance = math.hypot(x - 343, y - 80)
            if distance < 53:
                old = (y * width + x) * 4
                amount = int((1 - distance / 53) * 14)
                pixels[old] = min(255, pixels[old] + amount)
                pixels[old + 1] = min(255, pixels[old + 1] + amount)
                pixels[old + 2] = min(255, pixels[old + 2] + amount * 2)
    for x in range(width):
        hill = int(145 + 14 * math.sin(x * .019) + 10 * math.sin(x * .047 + 1.4))
        far = int(163 + 8 * math.sin(x * .031 + .8))
        for y in range(hill, height):
            set_pixel(pixels, width, x, y, (10, 28, 38, 255))
        for y in range(far, height):
            set_pixel(pixels, width, x, y, (7, 29, 28, 255))
    for x in range(0, width, 6):
        top = 150 + int(hash01(x, 37) * 26)
        canopy = 3 + int(hash01(x, 43) * 5)
        for y in range(top, 185):
            for dx in range(-canopy, canopy + 1):
                if hash01(x + dx, y) > .16:
                    set_pixel(pixels, width, x + dx, y, (4, 22, 24, 255))
    for y in range(188, height):
        for x in range(width):
            t = (y - 188) / 84.0
            set_pixel(pixels, width, x, y, (4, int(27 - t * 10), int(22 - t * 8), 255))
    for x in range(0, width, 3):
        base = 268 - int(hash01(x, 61) * 14)
        tip = base - 9 - int(hash01(x, 71) * 17)
        for y in range(tip, base):
            offset = int((base - y) * (hash01(x, 79) - .5) * .18)
            set_pixel(pixels, width, x + offset, y, (8, 49, 35, 255))
    return width, height, pixels


def make_glow(size: int = 64) -> Tuple[int, int, bytearray]:
    pixels = rgba_texture_pixels(size, size)
    center = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            radius = math.hypot(x - center, y - center) / center
            if radius < 1:
                alpha = int(210 * (1.0 - radius) ** 2.4)
                set_pixel(pixels, size, x, y, (255, 220, 95, alpha))
    return size, size, pixels


def make_firefly_sprite() -> Tuple[int, int, bytearray]:
    width, height = 20, 14
    pixels = rgba_texture_pixels(width, height)
    # Wings, outlined body, warm abdomen and head: deliberately readable near camera.
    for x, y in ((6, 4), (5, 5), (4, 6), (3, 7), (5, 8), (14, 4), (15, 5), (16, 6), (17, 7), (15, 8)):
        set_pixel(pixels, width, x, y, (161, 197, 177, 120))
    for x, y in ((8, 4), (9, 4), (10, 4), (8, 5), (9, 5), (10, 5), (8, 6), (9, 6), (10, 6), (9, 3)):
        set_pixel(pixels, width, x, y, (16, 28, 25, 255))
    for x, y in ((8, 7), (9, 7), (10, 7), (8, 8), (9, 8), (10, 8), (9, 9), (9, 10)):
        set_pixel(pixels, width, x, y, (255, 218, 71, 255))
    return width, height, pixels


def make_grass_sprite() -> Tuple[int, int, bytearray]:
    width, height = 18, 42
    pixels = rgba_texture_pixels(width, height)
    for blade in range(7):
        base = 4 + blade * 2
        tip_x = base + int((hash01(blade, 5) - .5) * 9)
        tip_y = int(hash01(blade, 9) * 16)
        for y in range(tip_y, height):
            progress = (y - tip_y) / max(1, height - tip_y)
            x = int(tip_x * (1 - progress) + base * progress)
            set_pixel(pixels, width, x, y, (13, 58, 39, 190))
            set_pixel(pixels, width, x + 1, y, (9, 45, 33, 180))
    return width, height, pixels


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

    def change_population(self, amount: int) -> None:
        target = int(clamp(len(self.fireflies) + amount, MIN_FIREFLIES, MAX_FIREFLIES))
        if target < len(self.fireflies):
            del self.fireflies[target:]
        else:
            self.fireflies.extend(self.new_firefly() for _ in range(target - len(self.fireflies)))

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


FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0), "A": (14, 17, 17, 31, 17, 17, 17), "C": (15, 16, 16, 16, 16, 16, 15),
    "D": (30, 17, 17, 17, 17, 17, 30), "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (15, 16, 16, 23, 17, 17, 15), "H": (17, 17, 17, 31, 17, 17, 17), "I": (31, 4, 4, 4, 4, 4, 31),
    "L": (16, 16, 16, 16, 16, 16, 31), "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14), "P": (30, 17, 17, 30, 16, 16, 16), "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "T": (31, 4, 4, 4, 4, 4, 4), "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4), "W": (17, 17, 17, 21, 21, 21, 10), "Y": (17, 17, 10, 4, 4, 4, 4),
    "0": (14, 17, 19, 21, 25, 17, 14), "1": (4, 12, 4, 4, 4, 4, 14), "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (30, 1, 1, 14, 1, 1, 30), "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14), "7": (31, 1, 2, 4, 8, 8, 8), "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 1, 14), ":": (0, 4, 0, 0, 4, 0, 0), "%": (17, 2, 4, 8, 16, 0, 17),
}


class FireflyApp:
    def __init__(self, sdl: SDL, fullscreen: bool = True, renderer: str = "auto") -> None:
        self.sdl, self.window, self.renderer = sdl, None, None
        self.textures: List[c.c_void_p] = []
        self.field = Field()
        self.show_status = False
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
            sdl.SetHint(b"SDL_TOUCH_MOUSE_EVENTS", b"0")
            sdl.SetHint(b"SDL_MOUSE_TOUCH_EVENTS", b"0")
            self.window, self.renderer, self.renderer_snapshot = self.select_renderer()
            self.renderer_name = self.renderer_snapshot.name
            self.accelerated = self.renderer_snapshot.accelerated
            sdl.RenderSetLogicalSize(self.renderer, LOGICAL_WIDTH, LOGICAL_HEIGHT)
            info = SDLRendererInfo()
            self.scene = self.texture(*make_scene(), SDL_BLENDMODE_NONE)
            self.glow_texture = self.texture(*make_glow(), SDL_BLENDMODE_ADD)
            self.fly_texture = self.texture(*make_firefly_sprite(), SDL_BLENDMODE_BLEND)
            self.grass_texture = self.texture(*make_grass_sprite(), SDL_BLENDMODE_BLEND)
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
            self.sdl.DestroyWindow(window)
            raise RuntimeError(self.sdl.error())
        info = SDLRendererInfo()
        status = self.sdl.GetRendererInfo(renderer, c.byref(info))
        if status != 0 or not valid_renderer(mode, info):
            detail = self.sdl.error() if status != 0 else "renderer flags=%#x do not satisfy %s mode" % (info.flags, mode)
            self.sdl.DestroyRenderer(renderer)
            self.sdl.DestroyWindow(window)
            raise RuntimeError(detail)
        # Show only a verified renderer. Fullscreen output size may settle here.
        self.sdl.ShowWindow(window)
        width, height = c.c_int(), c.c_int()
        if self.sdl.GetRendererOutputSize(renderer, c.byref(width), c.byref(height)) != 0:
            self.sdl.DestroyRenderer(renderer)
            self.sdl.DestroyWindow(window)
            raise RuntimeError(self.sdl.error())
        return window, renderer, info, (width.value, height.value)

    def snapshot(self, actual: str, info: SDLRendererInfo, output: Tuple[int, int], hardware_error: Optional[str]) -> RendererSnapshot:
        width, height = c.c_int(), c.c_int()
        self.sdl.GetWindowSize(self.window, c.byref(width), c.byref(height))
        driver = (self.sdl.GetCurrentVideoDriver() or b"unknown").decode("utf-8", "replace")
        return RendererSnapshot(self.requested_renderer, actual, (info.name or b"SDL").decode("utf-8", "replace"),
                                info.flags, driver, (width.value, height.value), output,
                                (info.max_texture_width, info.max_texture_height), hardware_error)

    def select_renderer(self):
        drivers = renderer_drivers(self.sdl)
        failures: List[str] = []
        if self.requested_renderer != "software":
            hardware = [(index, info) for index, info in drivers if valid_renderer("hardware", info)]
            # Vitrallis Shell's GLES2 compatibility floor is preferred when SDL advertises it.
            hardware.sort(key=lambda item: (item[1].name or b"").decode("utf-8", "replace") != "opengles2")
            for index, advertised in hardware:
                name = (advertised.name or b"unknown").decode("utf-8", "replace")
                for vsync in (True, False):
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
        for index, _ in drivers:
            advertised = SDLRendererInfo()
            if self.sdl.GetRenderDriverInfo(index, c.byref(advertised)) != 0 or not valid_renderer("software", advertised):
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
        self.sdl.SetTextureBlendMode(texture, blend)
        self.textures.append(texture)
        return texture

    def copy(self, texture, x: float, y: float, width: float, height: float, alpha: int = 255, angle: float = 0) -> None:
        self.sdl.SetTextureAlphaMod(texture, int(clamp(alpha, 0, 255)))
        destination = SDLRect(int(x - width / 2), int(y - height / 2), max(1, int(width)), max(1, int(height)))
        self.sdl.RenderCopyEx(self.renderer, texture, None, c.byref(destination), angle, None, SDL_FLIP_NONE)

    def draw_text(self, x: int, y: int, text: str, scale: int = 1, color=(209, 239, 183, 255)) -> None:
        self.sdl.SetRenderDrawColor(self.renderer, *color)
        cursor = x
        for char in text.upper():
            rows = FONT.get(char, FONT[" "])
            for row, bits in enumerate(rows):
                for column in range(5):
                    if bits & (1 << (4 - column)):
                        block = SDLRect(cursor + column * scale, y + row * scale, scale, scale)
                        self.sdl.RenderFillRect(self.renderer, c.byref(block))
            cursor += 6 * scale

    def draw_status(self) -> None:
        panel = SDLRect(10, 10, 172, 61)
        self.sdl.SetRenderDrawColor(self.renderer, 4, 14, 18, 215)
        self.sdl.RenderFillRect(self.renderer, c.byref(panel))
        self.draw_text(17, 16, "FIREFLY FIELD", 1)
        self.draw_text(17, 29, "FIREFLIES: %03d" % len(self.field.fireflies), 1, (170, 205, 167, 255))
        self.draw_text(17, 40, "FPS: %02d" % self.fps, 1, (170, 205, 167, 255))
        name = ("GPU " if self.accelerated else "SDL ") + self.renderer_name[:10]
        self.draw_text(17, 51, name, 1, (170, 205, 167, 255))

    def render(self) -> None:
        self.sdl.SetRenderDrawColor(self.renderer, 3, 10, 20, 255)
        self.sdl.RenderClear(self.renderer)
        destination = SDLRect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT)
        self.sdl.RenderCopy(self.renderer, self.scene, None, c.byref(destination))
        # Far insects are first, selling depth while leaving close sprites readable.
        for fly in sorted(self.field.fireflies, key=lambda item: item.depth):
            brightness = self.field.brightness(fly)
            glow_size = (15 + fly.depth * 31) * fly.size * (0.65 + brightness * .7) * self.field.glow
            self.copy(self.glow_texture, fly.x, fly.y, glow_size, glow_size, int(255 * brightness * self.field.glow))
            body_size = (6 + fly.depth * 9) * fly.size
            heading = math.degrees(math.atan2(fly.vy, fly.vx)) + 90
            self.copy(self.fly_texture, fly.x, fly.y, body_size * 1.35, body_size, int(80 + 175 * brightness), heading)
        # A handful of cheap texture copies gives the foreground a living edge.
        for index in range(19):
            x = index * 28 - 10
            sway = math.sin(self.field.time * .75 + index * .91) * (2 + index % 3)
            self.copy(self.grass_texture, x, 257, 20, 46, 180, sway)
        if 0 < self.field.shooting_star < .75:
            progress = 1 - self.field.shooting_star / .75
            self.copy(self.glow_texture, 70 + progress * 190, 45 + progress * 60, 24, 24, int(175 * (1 - progress)))
        if self.show_status:
            self.draw_status()
        self.sdl.RenderPresent(self.renderer)

    def handle_key(self, sym: int) -> None:
        # SDLK values are stable ASCII for these keys; arrows use SDL's 0x40000000 range.
        if sym in (27,): self.running = False
        elif sym in (32,): self.field.paused = not self.field.paused
        elif sym in (ord("r"), ord("R")): self.field.reseed(len(self.field.fireflies))
        elif sym in (ord("h"), ord("H")): self.show_status = not self.show_status
        elif sym in (273, 1073741906): self.field.change_population(10)
        elif sym in (274, 1073741905): self.field.change_population(-10)
        elif sym in (276, 1073741904): self.field.glow = clamp(self.field.glow - .1, .2, 1.4)
        elif sym in (275, 1073741903): self.field.glow = clamp(self.field.glow + .1, .2, 1.4)

    def events(self) -> None:
        event = (c.c_ubyte * 56)()
        while self.sdl.PollEvent(c.byref(event)):
            kind = c.c_uint32.from_buffer(event, 0).value
            if kind == SDL_QUIT:
                self.running = False
            elif kind == SDL_KEYDOWN:
                self.handle_key(c.c_int32.from_buffer(event, 20).value)
            elif kind == SDL_MOUSEMOTION:
                self.pointer = (float(c.c_int32.from_buffer(event, 20).value), float(c.c_int32.from_buffer(event, 24).value))
                self.field.pointer = self.pointer
            elif kind == SDL_MOUSEBUTTONDOWN:
                x, y = c.c_int32.from_buffer(event, 16).value, c.c_int32.from_buffer(event, 20).value
                self.field.pulse(float(x), float(y))

    def run(self) -> None:
        previous = time.monotonic()
        while self.running:
            now = time.monotonic()
            self.field.update(now - previous)
            previous = now
            self.events()
            self.render()
            self.frames += 1
            if now - self.fps_then >= 1:
                self.fps, self.frames, self.fps_then = self.frames, 0, now
            self.sdl.Delay(1)

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
