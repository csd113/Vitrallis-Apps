"""Generate the original Firefly Field package icon without image libraries."""
from pathlib import Path
import struct
import zlib


SIZE = 128


def pixel(x, y):
    horizon = 76
    if y < horizon:
        blue = 29 + y // 3
        return 8, 18 + y // 5, blue, 255
    if y < 100:
        return 9, 35 - (y - horizon) // 5, 30 - (y - horizon) // 7, 255
    return 5, 24, 20, 255


def build():
    rows = []
    for y in range(SIZE):
        row = bytearray([0])
        for x in range(SIZE):
            color = pixel(x, y)
            # A distant hill and foreground meadow.
            if y > 78 + ((x - 20) * (x - 20)) // 420 or y > 84 + ((x - 100) * (x - 100)) // 310:
                color = (7, 31, 27, 255)
            if y > 104:
                color = (4, 21, 18, 255)
            # The firefly's warm radial light.
            dx, dy = x - 65, y - 60
            d2 = dx * dx + dy * dy
            if d2 < 950:
                strength = max(0, 180 - d2 * 180 // 950)
                color = (min(255, color[0] + strength), min(255, color[1] + strength),
                         min(255, color[2] + strength // 4), 255)
            if (abs(dx) < 4 and abs(dy) < 7) or (abs(dx) < 12 and 4 < abs(dy) < 7):
                color = (238, 232, 171, 255) if dy < 2 else (255, 220, 73, 255)
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    Path(__file__).resolve().parents[1].joinpath("icon.png").write_bytes(build())
