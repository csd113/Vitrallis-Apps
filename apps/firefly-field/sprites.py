"""Ordered sprite batching with a small premultiplied-alpha atlas.

The additive glow and normal sprites share ONE / ONE_MINUS_SRC_ALPHA blending:
zero-alpha glow texels add light, while premultiplied bodies retain coverage.
Quad order is unchanged. No simulation state or texture is rebuilt per frame.
"""
import ctypes as c
import math


class SpriteBatch:
    def __init__(self, app, load_artwork, maximum):
        self.app = app
        lib = app.sdl.lib
        self.draw = getattr(lib, 'SDL_RenderGeometryRaw', None)
        compose = getattr(lib, 'SDL_ComposeCustomBlendMode', None)
        if self.draw is None or compose is None:
            raise RuntimeError('SDL geometry batching requires SDL 2.0.18+')
        self.draw.restype = c.c_int
        self.draw.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_int,
                              c.c_void_p, c.c_int, c.c_void_p, c.c_int,
                              c.c_int, c.c_void_p, c.c_int, c.c_int]
        compose.restype = c.c_int
        compose.argtypes = [c.c_int] * 6
        # SDL_BLENDFACTOR_ONE=2, ONE_MINUS_SRC_ALPHA=6, BLENDOPERATION_ADD=1.
        blend = compose(2, 6, 1, 2, 6, 1)
        width, height = 128, 68
        pixels = bytearray(width * height * 4)
        self.uvs = {}
        for name, x, y, w, h, additive in (('glow', 2, 2, 64, 64, True),
                                           ('firefly', 70, 2, 20, 14, False),
                                           ('grass', 70, 20, 18, 42, False)):
            _, _, data = load_artwork(name, w, h)
            for row in range(h):
                for column in range(w):
                    source = (row * w + column) * 4
                    dest = ((y + row) * width + x + column) * 4
                    alpha = data[source + 3]
                    for channel in range(3):
                        pixels[dest + channel] = (data[source + channel] * alpha + 127) // 255
                    pixels[dest + 3] = 0 if additive else alpha
            self.uvs[name] = (x / width, y / height, (x + w) / width, (y + h) / height)
        self.texture = app.texture(width, height, pixels, blend)
        self.maximum = maximum
        self.positions = (c.c_float * (maximum * 8))()
        self.colors = (c.c_ubyte * (maximum * 16))()
        self.coordinates = (c.c_float * (maximum * 8))()
        self.indices = (c.c_uint16 * (maximum * 6))()
        for quad in range(maximum):
            for index, vertex in enumerate((0, 1, 2, 0, 2, 3)):
                self.indices[quad * 6 + index] = quad * 4 + vertex
        self.count = 0
        # Probe support with one transparent degenerate quad before using the
        # batch. Software renderers may reject custom blend/geometry support.
        if self.draw(app.renderer, self.texture, self.positions, 8, self.colors, 4,
                     self.coordinates, 8, 4, self.indices, 6, 2) != 0:
            raise RuntimeError('SDL backend does not support ordered sprite geometry')

    def add(self, name, x, y, width, height, alpha=255, angle=0):
        if self.count >= self.maximum:
            raise RuntimeError('Sprite batch capacity exceeded')
        # Match SDL_RenderCopyEx integer destination rounding and center rotation.
        left, top = int(x - width / 2), int(y - height / 2)
        w, h = max(1, int(width)), max(1, int(height))
        cx, cy = w / 2, h / 2
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        u0, v0, u1, v1 = self.uvs[name]
        alpha = min(255, max(0, int(alpha)))
        p, color = self.count * 8, self.count * 16
        for i, (dx, dy, u, v) in enumerate(((-cx, -cy, u0, v0), (cx, -cy, u1, v0),
                                           (cx, cy, u1, v1), (-cx, cy, u0, v1))):
            self.positions[p + i * 2] = left + cx + dx * cosine - dy * sine
            self.positions[p + i * 2 + 1] = top + cy + dx * sine + dy * cosine
            self.coordinates[p + i * 2] = u
            self.coordinates[p + i * 2 + 1] = v
            for channel in range(4):
                self.colors[color + i * 4 + channel] = alpha
        self.count += 1

    def present(self):
        if self.count and self.draw(self.app.renderer, self.texture, self.positions, 8,
                                    self.colors, 4, self.coordinates, 8, self.count * 4,
                                    self.indices, self.count * 6, 2) != 0:
            raise RuntimeError('SDL sprite batch failed: ' + self.app.sdl.error())
        self.count = 0
