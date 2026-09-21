"""Pure playlist/timing logic and one bounded decoder worker; no Tk calls here."""
import math
from collections import OrderedDict
from dataclasses import dataclass
import os
import queue
import random
import select
import signal
import stat
import subprocess
import threading
import time

from PIL import Image, ImageOps
from animation_cache import AnimationCache, WINDOW
from media import (FORMATS, MAX_FRAMES, MAX_GIF_PIXELS, MAX_PIXELS,
                   MAX_ANIMATION_PIXELS, MAX_VIDEO_SECONDS, MediaError, Processes, video_command)


MAX_ANIMATION_BYTES = 8 * 1024 * 1024
MAX_STILL_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class GpuFrame:
    """RGBA bytes prepared off the UI thread and reused across GIF repeats."""
    size: tuple
    pixels: bytes
    mode = "RGBA"

    @property
    def width(self):
        return self.size[0]

    @property
    def height(self):
        return self.size[1]

    def tobytes(self):
        return self.pixels

    def convert(self, mode):
        return Image.frombytes("RGBA", self.size, self.pixels).convert(mode)

    @classmethod
    def from_image(cls, image):
        return cls(image.size, image.convert("RGBA").tobytes())


class Playlist:
    def __init__(self, items, settings, rng=None):
        self.items = [dict(item) for item in items]
        self.settings = dict(settings)
        self.rng = rng or random.Random()
        self.bad = set()
        self.cycle = []
        self.index = -1
        self._new_cycle(None)

    def _new_cycle(self, previous):
        self.cycle = [item for item in self.items if item["id"] not in self.bad]
        if self.settings["order"] == "shuffle":
            self.rng.shuffle(self.cycle)
            if len(self.cycle) > 1 and self.cycle[0]["id"] == previous:
                self.cycle[0], self.cycle[1] = self.cycle[1], self.cycle[0]
        self.index = -1

    @property
    def current(self):
        return self.cycle[self.index] if 0 <= self.index < len(self.cycle) else None

    def next(self):
        previous = self.current
        self.index += 1
        while self.index < len(self.cycle) and self.cycle[self.index]["id"] in self.bad:
            self.index += 1
        if self.index >= len(self.cycle):
            if not self.settings["loop"]:
                return None
            self._new_cycle(previous["id"] if previous else None)
            self.index = 0
        return self.current

    def previous(self):
        self.index = max(0, self.index - 1)
        while self.index > 0 and self.cycle[self.index]["id"] in self.bad:
            self.index -= 1
        if self.current and self.current["id"] in self.bad:
            return self.next()
        return self.current

    def failed(self):
        if self.current:
            self.bad.add(self.current["id"])
        return self.next()

    def upcoming(self):
        """Known playback order only; do not consume RNG for a future shuffle."""
        items = self.cycle[max(0, self.index):]
        if self.settings["loop"] and self.settings["order"] == "ordered":
            items += self.cycle[:max(0, self.index)]
        result, animations = [], 0
        for item in items:
            if item["id"] not in self.bad:
                result.append(item)
                if (item.get("kind") in ("gif", "webp")
                        and item.get("animated", item.get("kind") == "gif")):
                    animations += 1
                    if animations == WINDOW:
                        break
        return result


class PlaybackClock:
    def __init__(self, now=time.monotonic):
        self.now = now
        self.deadline = None
        self.remaining = 0
        self.paused = False

    def arm(self, seconds, continuous=False):
        # Advance animation deadlines from the previous presentation timeline,
        # not from completion of image upload, which otherwise slows every frame.
        now = self.now()
        origin = self.deadline if continuous and self.deadline is not None else now
        self.deadline = origin + max(0, seconds)
        self.remaining = max(0, self.deadline - now)

    def delay_ms(self):
        if self.paused or self.deadline is None:
            return 10
        return max(1, min(20, math.ceil((self.deadline - self.now()) * 1000)))

    def toggle(self):
        if self.deadline is not None:
            if self.paused:
                self.deadline = self.now() + self.remaining
            else:
                self.remaining = max(0, self.deadline - self.now())
        self.paused = not self.paused

    def ready(self):
        return not self.paused and (self.deadline is None or self.now() >= self.deadline)


def gif_seconds(value):
    if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        return 0.1
    return max(0.02, min(10, value / 1000))


def display_copy(source, size):
    copy = source.convert("RGBA")
    # Bilinear is enough for a downscaled screen copy and costs less CPU than LANCZOS.
    copy.thumbnail(size, Image.Resampling.BILINEAR)
    return copy


def drain(channel):
    while True:
        try:
            channel.get_nowait()
        except queue.Empty:
            return


class Decoder:
    def __init__(self, library):
        self.library = library
        self.commands = queue.Queue(maxsize=1)
        self.events = queue.Queue(maxsize=2)
        self.closed = threading.Event()
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.processes = Processes()
        self.process = None
        self.generation = 0
        self.animation_cache = AnimationCache(self._prepare_animation, lambda: MAX_ANIMATION_BYTES)
        self.still_lock = threading.Lock()
        self.still_cache = OrderedDict()
        self.still_bytes = 0
        self.thread = threading.Thread(target=self._work, name="carousel-decoder")
        self.thread.start()

    def stop(self, clear_cache=True):
        with self.lock:
            self.generation += 1
            self.cancel.set()
            if self.process is not None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            drain(self.commands)
            drain(self.events)
        if clear_cache:
            self.animation_cache.clear()
            self._clear_stills()

    def request(self, item, size, settings, gpu=False, upcoming=None):
        self.stop(clear_cache=False)
        with self.lock:
            self.cancel = threading.Event()
            # Bound display copies even on large external desktops.
            width, height = max(1, size[0]), max(1, size[1])
            scale = min(1, 1280 / width, 720 / height)
            bounded = (max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2))
            options = dict(settings, gpu=bool(gpu))
            self.animation_cache.update(upcoming if upcoming is not None else [item], bounded, bool(gpu))
            self.commands.put_nowait((self.generation, item, bounded, options, self.cancel))
            return self.generation

    def _emit(self, cancel, generation, kind, value=None, seconds=0):
        while not self.closed.is_set() and not cancel.is_set():
            try:
                self.events.put((generation, kind, value, seconds), timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _work(self):
        while not self.closed.is_set():
            try:
                generation, item, size, settings, cancel = self.commands.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self._still_from_cache(item, size, settings, cancel, generation):
                    continue
                with self.library.open_item(item) as stream:
                    if os.fstat(stream.fileno()).st_size != item["size"]:
                        raise MediaError("Media size no longer matches the library")
                    if item["kind"] == "webm":
                        self._video(stream, size, settings, cancel, generation)
                    else:
                        self._image(stream, size, settings, cancel, generation, item)
                self._emit(cancel, generation, "done")
            except (OSError, ValueError, EOFError, SyntaxError, subprocess.SubprocessError,
                    Image.DecompressionBombError) as error:
                message = str(error) if isinstance(error, MediaError) else "File missing, corrupt or no longer readable"
                self._emit(cancel, generation, "error", message)

    def _still_from_cache(self, item, size, settings, cancel, generation):
        """One stat decides whether unchanged still bytes can skip open and decode."""
        if item.get("animated", item.get("kind") in ("gif", "webm")):
            return False
        key = (item["id"], tuple(size))
        try:
            info = os.stat(self.library.paths.media / item["id"], follow_symlinks=False)
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode) or info.st_size != item["size"]:
            return False
        with self.still_lock:
            entry = self.still_cache.get(key)
            if entry is None:
                return False
            self.still_cache.move_to_end(key)
        if not self._emit(cancel, generation, "frame", entry[0], settings["image_seconds"]):
            return True
        self._emit(cancel, generation, "done")
        return True

    def _still_store(self, item, size, image):
        weight = image.width * image.height * len(image.mode)
        if weight > MAX_STILL_BYTES:
            return
        key = (item["id"], tuple(size))
        with self.still_lock:
            previous = self.still_cache.pop(key, None)
            if previous is not None:
                self.still_bytes -= previous[1]
            self.still_cache[key] = (image, weight)
            self.still_bytes += weight
            while self.still_bytes > MAX_STILL_BYTES and self.still_cache:
                _, (_, dropped) = self.still_cache.popitem(last=False)
                self.still_bytes -= dropped

    def _clear_stills(self):
        with self.still_lock:
            self.still_cache.clear()
            self.still_bytes = 0

    def _image(self, stream, size, settings, cancel, generation, item):
        with Image.open(stream, formats=FORMATS) as source:
            if source.width * source.height > MAX_PIXELS:
                raise MediaError("Image exceeds pixel limit")
            if source.format in ("GIF", "WEBP") and getattr(source, "is_animated", False):
                self._animation(source, size, settings, cancel, generation, item)
                return
            source.draft("RGB", size)
            source.thumbnail(size, Image.Resampling.LANCZOS)
            oriented = ImageOps.exif_transpose(source)
            still = display_copy(oriented, size)
            self._still_store(item, size, still)
            self._emit(cancel, generation, "frame", still, settings["image_seconds"])

    def _animation(self, source, size, settings, cancel, generation, item):
        if source.width * source.height > MAX_GIF_PIXELS:
            raise MediaError("Animation frame exceeds pixel limit")
        prepared = self.animation_cache.wait(item=item, size=size,
                                             gpu=bool(settings.get("gpu")), cancel=cancel)
        if cancel.is_set():
            return
        if prepared:
            for _ in range(settings["repeats"]):
                for frame, seconds in prepared:
                    if not self._emit(cancel, generation, "frame", frame, seconds):
                        return
            return
        cache, cached_bytes, cache_complete = [], 0, False
        for _ in range(settings["repeats"]):
            if cache_complete:
                for frame, seconds in cache:
                    if not self._emit(cancel, generation, "frame", frame, seconds):
                        return
                continue
            source.seek(0)  # GIF and WebP both rewind and replay forward from the start.
            for frame, seconds in self._animation_frames(source, size, settings.get("gpu"), cancel):
                if cache is not None:
                    cached_bytes += frame.width * frame.height * 4
                    if cached_bytes <= MAX_ANIMATION_BYTES:
                        cache.append((frame, seconds))
                    else:
                        cache = None
                if not self._emit(cancel, generation, "frame", frame, seconds):
                    return
            if cancel.is_set():
                return
            cache_complete = cache is not None

    def _animation_frames(self, source, size, gpu, cancel, deadline=None):
        """Yield (frame, seconds) forward through GIF or animated WebP frames."""
        frames, pixels = 0, 0
        while not cancel.is_set() and not self.closed.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                raise MediaError("Animation exceeds frame/decode budget")
            if source.width * source.height > MAX_GIF_PIXELS:
                raise MediaError("Animation frame exceeds pixel limit")
            # Copy pixels first: WebP reports the previous frame's duration until
            # the current frame is loaded.
            frame = GpuFrame.from_image(source) if gpu else display_copy(source, size)
            seconds = gif_seconds(source.info.get("duration", 100))
            frames += 1
            pixels += source.width * source.height
            if frames > MAX_FRAMES or pixels > MAX_ANIMATION_PIXELS:
                raise MediaError("Animation exceeds frame budget")
            yield frame, seconds
            try:
                source.seek(frames)
            except EOFError:
                return

    def _prepare_animation(self, item, size, gpu, cancel):
        with self.library.open_item(item) as stream, Image.open(stream, formats=FORMATS) as source:
            if os.fstat(stream.fileno()).st_size != item["size"]:
                raise MediaError("Media size no longer matches the library")
            deadline = time.monotonic() + 30
            yield from self._animation_frames(source, size, gpu, cancel, deadline)

    def _video(self, stream, size, settings, cancel, generation):
        length = size[0] * size[1] * 3
        for _ in range(settings["repeats"]):
            if cancel.is_set():
                return
            stream.seek(0)
            process = self.processes.start(video_command(stream.fileno(), size) +
                                           ["-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                                           pass_fds=(stream.fileno(),), stdout=subprocess.PIPE,
                                           bufsize=0)
            with self.lock:
                self.process = process
            frames, buffer = 0, bytearray()
            deadline = time.monotonic() + 10
            try:
                while not cancel.is_set() and not self.closed.is_set():
                    if time.monotonic() > deadline:
                        raise MediaError("WebM decoder stalled")
                    if not select.select([process.stdout], [], [], 0.1)[0]:
                        continue
                    chunk = os.read(process.stdout.fileno(), min(65536, length - len(buffer)))
                    if not chunk:
                        if buffer or not frames or process.wait(timeout=1) != 0:
                            raise MediaError("WebM decoder found corrupt video")
                        break
                    buffer.extend(chunk)
                    if len(buffer) == length:
                        frame = Image.frombytes("RGB", size, bytes(buffer))
                        buffer.clear()
                        frames += 1
                        if frames > MAX_VIDEO_SECONDS * 20 + 1:
                            raise MediaError("Video exceeds playback limit")
                        if not self._emit(cancel, generation, "frame", frame, 0.05):
                            return
                        deadline = time.monotonic() + 10
            finally:
                self.processes.finish(process)
                process.stdout.close()
                with self.lock:
                    self.process = None

    def close(self):
        self.closed.set()
        self.stop()
        self.animation_cache.close()
        self.processes.close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("Decoder worker did not stop within 3 seconds")
