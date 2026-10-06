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
            u0, v0, u1, v1 = x / width, y / height, (x + w) / width, (y + h) / height
            self.uvs[name] = (u0, v0, u1, v0, u1, v1, u0, v1)
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
        self.last_sprite = [None] * maximum
        self.last_alpha = [-1] * maximum
        self.color_address = c.addressof(self.colors)
        # Probe support with one transparent degenerate quad before using the
        # batch. Software renderers may reject custom blend/geometry support.
        if self.draw(app.renderer, self.texture, self.positions, 8, self.colors, 4,
                     self.coordinates, 8, 4, self.indices, 6, 2) != 0:
            raise RuntimeError('SDL backend does not support ordered sprite geometry')

    def add(self, name, x, y, width, height, alpha=255, angle=0):
        if not 0 <= self.count < self.maximum:
            raise RuntimeError('Sprite batch capacity exceeded')
        # Validate the atlas identity before touching the packed buffers.
        uv = self.uvs[name]
        left, top = int(x - width / 2), int(y - height / 2)
        w, h = max(1, int(width)), max(1, int(height))
        p = self.count * 8
        if angle:
            cx, cy = w / 2, h / 2
            radians = math.radians(angle)
            cosine, sine = math.cos(radians), math.sin(radians)
            cos_x, sin_y = cx * cosine, cy * sine
            sin_x, cos_y = cx * sine, cy * cosine
            px, py = left + cx, top + cy
            self.positions[p:p + 8] = (px - cos_x + sin_y, py - sin_x - cos_y,
                                       px + cos_x + sin_y, py + sin_x - cos_y,
                                       px + cos_x - sin_y, py + sin_x + cos_y,
                                       px - cos_x - sin_y, py - sin_x + cos_y)
        else:
            self.positions[p:p + 8] = (left, top, left + w, top,
                                       left + w, top + h, left, top + h)
        if self.last_sprite[self.count] != name:
            self.coordinates[p:p + 8] = uv
            self.last_sprite[self.count] = name
        alpha = min(255, max(0, int(alpha)))
        if self.last_alpha[self.count] != alpha:
            # Four RGBA vertices share one byte value. Count is checked above,
            # so this fixed 16-byte write stays in the retained color array.
            c.memset(self.color_address + self.count * 16, alpha, 16)
            self.last_alpha[self.count] = alpha
        self.count += 1

    def present(self):
        if self.count and self.draw(self.app.renderer, self.texture, self.positions, 8,
                                    self.colors, 4, self.coordinates, 8, self.count * 4,
                                    self.indices, self.count * 6, 2) != 0:
            raise RuntimeError('SDL sprite batch failed: ' + self.app.sdl.error())
        self.count = 0
