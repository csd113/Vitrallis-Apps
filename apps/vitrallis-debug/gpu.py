"""Optional X11 EGL/GLES2 pulse. Uses system libraries, never a CPU fallback.

All methods run on Tk's main thread. A native child surface stays above Canvas
items; only two uniforms and a single triangle are submitted for each frame.
"""
from __future__ import annotations

import ctypes as c
from ctypes.util import find_library
import re


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
void main() { gl_Position = vec4(position, 0.0, 1.0); }
"""
FRAGMENT = b"""
precision mediump float;
uniform vec2 resolution;
uniform float elapsed;
void main() {
    vec2 p = (gl_FragCoord.xy - resolution * 0.5) / min(resolution.x, resolution.y);
    float r = length(p);
    float fade = smoothstep(0.0, 0.6, elapsed) * (1.0 - smoothstep(6.8, 8.0, elapsed));
    float wave = fract(r * 2.8 - elapsed * 0.42);
    float rings = (1.0 - smoothstep(0.012, 0.033, abs(wave - 0.5))) * (1.0 - smoothstep(0.2, 1.0, r));
    float halo = 0.022 / (0.05 + abs(r - 0.16 - 0.012 * sin(elapsed * 2.0)));
    vec2 grid = abs(fract(p * 10.0 + 0.5) - 0.5);
    float guides = 1.0 - smoothstep(0.008, 0.018, min(grid.x, grid.y));
    float core = 1.0 - smoothstep(0.025, 0.055, r);
    vec3 mint = vec3(0.32, 0.88, 0.74);
    vec3 blue = vec3(0.18, 0.44, 0.69);
    vec3 color = vec3(0.035, 0.06, 0.08) + guides * 0.025;
    color += fade * (mint * (rings * 0.8 + core) + blue * halo);
    gl_FragColor = vec4(color, 1.0);
}
"""


def _bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


class PulseRenderer:
    def __init__(self, widget) -> None:
        self.display = self.surface = self.context = self.xdisplay = None
        self.egl = self.gl = self.x11 = None
        self.program = 0
        self.buffer = c.c_uint(0)
        self.renderer = ""
        self.api_version = ""
        if widget.tk.call("tk", "windowingsystem") != "x11":
            raise GpuUnavailable("GPU Pulse needs an X11 desktop with EGL and OpenGL ES 2.")
        # Some older EGL drivers crash on an unmapped native child window.
        # Check before loading/calling them, including when launch is minimized.
        if not widget.winfo_viewable():
            raise GpuUnavailable("GPU Pulse needs a visible window.")
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
            ("glGetUniformLocation", integer, (uint, c.c_char_p)),
            ("glUniform1f", None, (integer, c.c_float)),
            ("glUniform2f", None, (integer, c.c_float, c.c_float)),
            ("glViewport", None, (integer, integer, integer, integer)),
            ("glDrawArrays", None, (uint, integer, integer)),
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
        self.surface = self.egl.eglCreateWindowSurface(self.display, chosen, widget.winfo_id(), None)
        if not self.context or not self.surface or not self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context):
            raise GpuUnavailable("Cannot create an OpenGL ES window surface.")
        self.renderer = (self.gl.glGetString(0x1F01) or b"").decode("utf-8", "replace")
        self.api_version = (self.gl.glGetString(0x1F02) or b"").decode("utf-8", "replace")
        if not hardware_renderer(self.renderer):
            raise GpuUnavailable(f"Hardware rendering is unavailable ({self.renderer or 'unknown renderer'}). Pulse is disabled.")
        self.egl.eglSwapInterval(self.display, 1)

    def _shader(self, kind: int, source: bytes) -> int:
        shader = self.gl.glCreateShader(kind)
        text = c.c_char_p(source)
        self.gl.glShaderSource(shader, 1, c.byref(text), None)
        self.gl.glCompileShader(shader)
        status = c.c_int()
        self.gl.glGetShaderiv(shader, 0x8B81, c.byref(status))
        if not status.value:
            self.gl.glDeleteShader(shader)
            raise GpuUnavailable("The GPU could not compile the Pulse shader.")
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
                raise GpuUnavailable("The GPU could not link the Pulse shader.")
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
        self.resolution = self.gl.glGetUniformLocation(self.program, b"resolution")
        self.elapsed = self.gl.glGetUniformLocation(self.program, b"elapsed")

    def draw(self, elapsed: float, width: int, height: int) -> None:
        self.gl.glViewport(0, 0, width, height)
        self.gl.glUniform2f(self.resolution, width, height)
        self.gl.glUniform1f(self.elapsed, elapsed)
        self.gl.glDrawArrays(0x0004, 0, 3)
        if not self.egl.eglSwapBuffers(self.display, self.surface):
            raise GpuUnavailable("The GPU surface was lost. Pulse has stopped.")

    def close(self) -> None:
        if self.display and self.egl:
            if self.context and self.surface:
                current = self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context)
                if current and self.gl:
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
        self.program, self.buffer.value = 0, 0
