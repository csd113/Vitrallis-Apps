"""Bounded thumbnail worker and in-memory cache; original files stay private."""
from collections import OrderedDict
import io
import os
from pathlib import Path
import subprocess
import sys
import threading

from PIL import Image, ImageOps
from media import FORMATS, MAX_PIXELS, MediaError, video_command

THUMB_SIZE = (128, 80)
MAX_THUMB = 64 * 1024
CACHE_BYTES = 2 * 1024 * 1024


class Thumbnails:
    def __init__(self, library, processes, decode_lock):
        self.library, self.processes, self.decode_lock = library, processes, decode_lock
        self.cache = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def get(self, item):
        # IDs refer to immutable blobs. Removed entries age out of the bounded LRU.
        with self.lock:
            cached = self.cache.get(item['id'])
            if cached is not None:
                self.cache.move_to_end(item['id'])
                return cached
        with self.decode_lock:
            with self.lock:
                if item['id'] in self.cache:
                    return self.cache[item['id']]
            with self.library.open_item(item) as stream:
                child = self.processes.start([sys.executable, '-B', str(Path(__file__).resolve()),
                                              str(stream.fileno()), item['kind']],
                                             pass_fds=(stream.fileno(),), stdout=subprocess.PIPE)
                try:
                    raw, _ = child.communicate(timeout=12)
                    if child.returncode or not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) > MAX_THUMB:
                        raw = placeholder()
                except subprocess.TimeoutExpired:
                    raw = placeholder()
                finally:
                    self.processes.finish(child)
            with self.lock:
                while self.cache and self.size + len(raw) > CACHE_BYTES:
                    _, old = self.cache.popitem(last=False)
                    self.size -= len(old)
                self.cache[item['id']] = raw
                self.size += len(raw)
            return raw


def encoded(image):
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def placeholder():
    image = Image.new('RGB', THUMB_SIZE, '#223232')
    image.paste('#adbbb3', (44, 25, 84, 55))
    image.paste('#223232', (48, 29, 80, 51))
    return encoded(image)


def thumbnail(stream, kind):
    if kind == 'webm':
        result = subprocess.run(video_command(stream.fileno(), THUMB_SIZE) +
                                ['-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                                pass_fds=(stream.fileno(),), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=8, check=False)
        if result.returncode or len(result.stdout) != THUMB_SIZE[0] * THUMB_SIZE[1] * 3:
            raise MediaError('Preview unavailable')
        return Image.frombytes('RGB', THUMB_SIZE, result.stdout)
    with Image.open(stream, formats=FORMATS) as source:
        if source.width * source.height > MAX_PIXELS:
            raise MediaError('Preview exceeds pixel limit')
        source.draft('RGB', THUMB_SIZE)
        source.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
        return ImageOps.exif_transpose(source).convert('RGBA')


def main():
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        # FFmpeg shared-library mappings need more virtual space on 64-bit hosts.
        limit = (1024 if sys.maxsize > 2**32 else 256) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    try:
        with os.fdopen(int(sys.argv[1]), 'rb') as stream:
            raw = encoded(thumbnail(stream, sys.argv[2]))
        if len(raw) > MAX_THUMB:
            raw = placeholder()
    except (OSError, ValueError, EOFError, SyntaxError, subprocess.SubprocessError,
            Image.DecompressionBombError):
        raw = placeholder()
    sys.stdout.buffer.write(raw)


if __name__ == '__main__':
    main()
