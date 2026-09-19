"""Optional X11 EGL/GLES2 image presentation through system libraries.

All methods run on Tk's main thread. A native child surface stays above Canvas
items; GIF decoding stays in Pillow; texture filtering and presentation run on the GPU.
"""
from __future__ import annotations

import ctypes as c
from ctypes.util import find_library
import re
import logging


class GpuUnavailable(RuntimeError):
    """A usable hardware context could not be created."""


def hardware_renderer(renderer: str) -> bool:
    """Conservatively refuse software and unrecognized renderer strings."""
    name = renderer.lower()
    if any(token in name for token in ("llvmpipe", "softpipe", "swrast", "software", "swiftshader", "lavapipe", "virgl")):
        return False
    return bool(re.search(r"mali|lima|panfrost|panthor|adreno|freedreno|vivante|etnaviv|powervr|tegra|nvidia|radeon|\bamd\b|intel|iris|\bv3d\b|\bvc4\b|videocore", name))


VERTEX = b"""
attribute vec2 position;
varying vec2 uv;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
    uv = vec2((position.x + 1.0) * 0.5, (1.0 - position.y) * 0.5);
}
"""
FRAGMENT = b"""
precision mediump float;
varying vec2 uv;
uniform sampler2D image;
void main() {
    vec4 pixel = texture2D(image, uv);
    gl_FragColor = vec4(pixel.rgb * pixel.a, 1.0);
}
"""


def _bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


class ImageRenderer:
    def __init__(self, widget) -> None:
        self.display = self.surface = self.context = self.xdisplay = None
        self.egl = self.gl = self.x11 = None
        self.program = 0
        self.buffer = c.c_uint(0)
        self.texture = c.c_uint(0)
        self.image_size = None
        self.max_texture = c.c_int()
        self.renderer = ""
        self.api_version = ""
        if widget.tk.call("tk", "windowingsystem") != "x11":
            raise GpuUnavailable("Accelerated playback needs an X11 desktop with EGL and OpenGL ES 2.")
        # Some older EGL drivers crash on an unmapped native child window.
        # Check before loading/calling them, including when launch is minimized.
        if not widget.winfo_viewable():
            raise GpuUnavailable("Accelerated playback needs a visible window.")
        try:
            self._load()
            self._context(widget)
            self._program()
        except (OSError, AttributeError, GpuUnavailable) as error:
            self.close()
            raise GpuUnavailable(str(error)) from error

    def _load(self) -> None:
        libraries = []
        for name in ("X11", "EGL", "GLESv2"):
            path = find_library(name)
            if not path:
                raise GpuUnavailable(f"System {name} library is unavailable.")
            libraries.append(c.CDLL(path))
        self.x11, self.egl, self.gl = libraries
        ptr, integer, uint = c.c_void_p, c.c_int, c.c_uint
        ip = c.POINTER(integer)
        _bind(self.x11, "XOpenDisplay", ptr, c.c_char_p)
        _bind(self.x11, "XCloseDisplay", integer, ptr)
        specs = (
            ("eglGetDisplay", ptr, (ptr,)),
            ("eglInitialize", uint, (ptr, ip, ip)),
            ("eglBindAPI", uint, (uint,)),
            ("eglChooseConfig", uint, (ptr, ip, c.POINTER(ptr), integer, ip)),
            ("eglGetConfigAttrib", uint, (ptr, ptr, integer, ip)),
            ("eglCreateWindowSurface", ptr, (ptr, ptr, c.c_ulong, ip)),
            ("eglCreateContext", ptr, (ptr, ptr, ptr, ip)),
            ("eglMakeCurrent", uint, (ptr, ptr, ptr, ptr)),
            ("eglSwapInterval", uint, (ptr, integer)),
            ("eglSwapBuffers", uint, (ptr, ptr)),
            ("eglDestroySurface", uint, (ptr, ptr)),
            ("eglDestroyContext", uint, (ptr, ptr)),
            ("eglTerminate", uint, (ptr,)),
        )
        for name, result, arguments in specs:
            _bind(self.egl, name, result, *arguments)
        specs = (
            ("glGetString", c.c_char_p, (uint,)),
            ("glCreateShader", uint, (uint,)),
            ("glShaderSource", None, (uint, integer, c.POINTER(c.c_char_p), ip)),
            ("glCompileShader", None, (uint,)),
            ("glGetShaderiv", None, (uint, uint, ip)),
            ("glDeleteShader", None, (uint,)),
            ("glCreateProgram", uint, ()),
            ("glAttachShader", None, (uint, uint)),
            ("glBindAttribLocation", None, (uint, uint, c.c_char_p)),
            ("glLinkProgram", None, (uint,)),
            ("glGetProgramiv", None, (uint, uint, ip)),
            ("glUseProgram", None, (uint,)),
            ("glDeleteProgram", None, (uint,)),
            ("glGenBuffers", None, (integer, c.POINTER(uint))),
            ("glBindBuffer", None, (uint, uint)),
            ("glBufferData", None, (uint, c.c_ssize_t, ptr, uint)),
            ("glDeleteBuffers", None, (integer, c.POINTER(uint))),
            ("glEnableVertexAttribArray", None, (uint,)),
            ("glVertexAttribPointer", None, (uint, integer, uint, c.c_ubyte, integer, ptr)),
            ("glViewport", None, (integer, integer, integer, integer)),
            ("glDrawArrays", None, (uint, integer, integer)),
        )
        specs += (
            ("glGetIntegerv", None, (uint, ip)),
            ("glGetError", uint, ()),
            ("glGenTextures", None, (integer, c.POINTER(uint))),
            ("glDeleteTextures", None, (integer, c.POINTER(uint))),
            ("glBindTexture", None, (uint, uint)),
            ("glTexParameteri", None, (uint, uint, integer)),
            ("glPixelStorei", None, (uint, integer)),
            ("glTexImage2D", None, (uint, integer, integer, integer, integer, integer, uint, uint, ptr)),
            ("glTexSubImage2D", None, (uint, integer, integer, integer, integer, integer, uint, uint, ptr)),
            ("glClearColor", None, (c.c_float, c.c_float, c.c_float, c.c_float)),
            ("glClear", None, (uint,)),
        )
        for name, result, arguments in specs:
            _bind(self.gl, name, result, *arguments)

    def _context(self, widget) -> None:
        self.xdisplay = self.x11.XOpenDisplay(None)
        if not self.xdisplay:
            raise GpuUnavailable("Cannot open the X11 display.")
        self.display = self.egl.eglGetDisplay(self.xdisplay)
        if not self.display or not self.egl.eglInitialize(self.display, None, None):
            raise GpuUnavailable("EGL could not initialize this display.")
        if not self.egl.eglBindAPI(0x30A0):  # EGL_OPENGL_ES_API
            raise GpuUnavailable("OpenGL ES is unavailable.")
        attributes = (c.c_int * 5)(0x3033, 4, 0x3040, 4, 0x3038)  # WINDOW_BIT, ES2_BIT, NONE
        configs, count = (c.c_void_p * 128)(), c.c_int()
        if not self.egl.eglChooseConfig(self.display, attributes, configs, 128, c.byref(count)):
            raise GpuUnavailable("No EGL window configuration is available.")
        visual = int(widget.winfo_visualid(), 0)
        chosen = None
        for config in configs[:count.value]:
            ident = c.c_int()
            if self.egl.eglGetConfigAttrib(self.display, config, 0x302E, c.byref(ident)) and ident.value == visual:
                chosen = config
                break
        if not chosen:
            raise GpuUnavailable("EGL cannot match the desktop's window visual.")
        context_attributes = (c.c_int * 3)(0x3098, 2, 0x3038)
        self.context = self.egl.eglCreateContext(self.display, chosen, None, context_attributes)
        surface_attributes = (c.c_int * 3)(0x3086, 0x3084, 0x3038)  # RENDER_BUFFER, BACK_BUFFER, NONE
        self.surface = self.egl.eglCreateWindowSurface(self.display, chosen, widget.winfo_id(), surface_attributes)
        if not self.context or not self.surface or not self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context):
            raise GpuUnavailable("Cannot create an OpenGL ES window surface.")
        self.renderer = (self.gl.glGetString(0x1F01) or b"").decode("utf-8", "replace")
        self.api_version = (self.gl.glGetString(0x1F02) or b"").decode("utf-8", "replace")
        if not hardware_renderer(self.renderer):
            raise GpuUnavailable(f"Hardware rendering is unavailable ({self.renderer or 'unknown renderer'}). Using Tk presentation.")
        # EGL window surfaces render into a backbuffer. Keep animation deadlines
        # independent of swap completion; the backend owns vblank synchronization.
        maximum_swap = c.c_int()
        supports_sync = self.egl.eglGetConfigAttrib(self.display, chosen, 0x303C, c.byref(maximum_swap))
        self.vsync = bool(supports_sync and maximum_swap.value >= 1 and self.egl.eglSwapInterval(self.display, 1))
        if not self.vsync:
            logging.warning("EGL VSync unavailable; buffered playback is limited to 30 FPS")

    def _shader(self, kind: int, source: bytes) -> int:
        shader = self.gl.glCreateShader(kind)
        text = c.c_char_p(source)
        self.gl.glShaderSource(shader, 1, c.byref(text), None)
        self.gl.glCompileShader(shader)
        status = c.c_int()
        self.gl.glGetShaderiv(shader, 0x8B81, c.byref(status))
        if not status.value:
            self.gl.glDeleteShader(shader)
            raise GpuUnavailable("The GPU could not compile the image shader.")
        return shader

    def _program(self) -> None:
        shaders = []
        try:
            shaders.append(self._shader(0x8B31, VERTEX))
            shaders.append(self._shader(0x8B30, FRAGMENT))
            self.program = self.gl.glCreateProgram()
            for shader in shaders:
                self.gl.glAttachShader(self.program, shader)
            self.gl.glBindAttribLocation(self.program, 0, b"position")
            self.gl.glLinkProgram(self.program)
            status = c.c_int()
            self.gl.glGetProgramiv(self.program, 0x8B82, c.byref(status))
            if not status.value:
                raise GpuUnavailable("The GPU could not link the image shader.")
        finally:
            for shader in shaders:
                self.gl.glDeleteShader(shader)
        self.gl.glUseProgram(self.program)
        vertices = (c.c_float * 6)(-1, -1, 3, -1, -1, 3)
        self.gl.glGenBuffers(1, c.byref(self.buffer))
        self.gl.glBindBuffer(0x8892, self.buffer.value)
        self.gl.glBufferData(0x8892, c.sizeof(vertices), vertices, 0x88E4)
        self.gl.glEnableVertexAttribArray(0)
        self.gl.glVertexAttribPointer(0, 2, 0x1406, 0, 0, None)
        self.gl.glGenTextures(1, c.byref(self.texture))
        self.gl.glBindTexture(0x0DE1, self.texture.value)
        for parameter, value in ((0x2801, 0x2601), (0x2800, 0x2601),
                                 (0x2802, 0x812F), (0x2803, 0x812F)):
            self.gl.glTexParameteri(0x0DE1, parameter, value)
        self.gl.glPixelStorei(0x0CF5, 1)
        self.gl.glGetIntegerv(0x0D33, c.byref(self.max_texture))
        self._check()

    def _current(self):
        if not self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context):
            raise GpuUnavailable("The GPU surface is unavailable.")

    def _check(self):
        if self.gl.glGetError():
            raise GpuUnavailable("The GPU rejected an image operation.")

    def present(self, image, width: int, height: int) -> None:
        if max(image.size) > self.max_texture.value:
            raise GpuUnavailable("Image exceeds the GPU texture size limit.")
        self._current()
        rgba = image if image.mode == "RGBA" else image.convert("RGBA")
        pixels = rgba.tobytes()
        self.gl.glBindTexture(0x0DE1, self.texture.value)
        if image.size != self.image_size:
            self.gl.glTexImage2D(0x0DE1, 0, 0x1908, image.width, image.height, 0,
                                 0x1908, 0x1401, pixels)
        else:
            self.gl.glTexSubImage2D(0x0DE1, 0, 0, 0, image.width, image.height,
                                    0x1908, 0x1401, pixels)
        self._check()
        self.image_size = image.size
        self.repaint(width, height)

    def clear(self) -> None:
        self._current()
        self.image_size = None
        self.gl.glClearColor(0, 0, 0, 1)
        self.gl.glClear(0x4000)
        if not self.egl.eglSwapBuffers(self.display, self.surface):
            raise GpuUnavailable("The GPU surface was lost.")

    def repaint(self, width: int, height: int) -> None:
        if self.image_size is None or width <= 0 or height <= 0:
            return
        self._current()
        image_width, image_height = self.image_size
        scale = min(1.0, width / image_width, height / image_height)
        fitted_width, fitted_height = max(1, round(image_width * scale)), max(1, round(image_height * scale))
        self.gl.glClearColor(0, 0, 0, 1)
        self.gl.glClear(0x4000)
        self.gl.glViewport((width - fitted_width) // 2, (height - fitted_height) // 2,
                           fitted_width, fitted_height)
        self.gl.glDrawArrays(0x0004, 0, 3)
        self._check()
        if not self.egl.eglSwapBuffers(self.display, self.surface):
            raise GpuUnavailable("The GPU surface was lost. Using Tk presentation.")

    def close(self) -> None:
        if self.display and self.egl:
            if self.context and self.surface:
                current = self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context)
                if current and self.gl:
                    if self.texture.value:
                        self.gl.glDeleteTextures(1, c.byref(self.texture))
                    if self.buffer.value:
                        self.gl.glDeleteBuffers(1, c.byref(self.buffer))
                    if self.program:
                        self.gl.glDeleteProgram(self.program)
            self.egl.eglMakeCurrent(self.display, None, None, None)
            if self.surface:
                self.egl.eglDestroySurface(self.display, self.surface)
            if self.context:
                self.egl.eglDestroyContext(self.display, self.context)
            self.egl.eglTerminate(self.display)
        if self.xdisplay and self.x11:
            self.x11.XCloseDisplay(self.xdisplay)
        self.display = self.surface = self.context = self.xdisplay = None
        self.program, self.buffer.value, self.texture.value = 0, 0, 0
        self.image_size = None
