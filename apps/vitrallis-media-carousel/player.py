"""Pure playlist/timing logic and bounded decoders; no Tk calls here.

Decoding always happens off the UI thread and always ahead of the presentation
deadline: the decoder owns a small bounded look-ahead, the animation cache keeps
prepared frames in RAM, and FFmpeg video is drained by its own reader thread so
neither the pipe nor the presentation loop can stall the other.
"""
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
import sys
import threading
import time

from PIL import Image, ImageOps
from animation_cache import AnimationCache, WINDOW
from media import (FORMATS, MAX_FRAMES, MAX_GIF_PIXELS, MAX_PIXELS,
                   MAX_ANIMATION_PIXELS, MAX_VIDEO_SECONDS, MAX_VIDEO_FPS,
                   MediaError, Processes, playback_fps, video_command, video_details)
from multimedia import DetectionCancelled, video_backend

MAX_ANIMATION_BYTES = 8 * 1024 * 1024
MAX_STILL_BYTES = 8 * 1024 * 1024

# Decoded frames buffered ahead of the presentation loop. Bounded, so a slow
# screen can never let decoding run away with memory.
LOOKAHEAD = 6
VIDEO_QUEUE_BYTES = 3 * 1024 * 1024
VIDEO_QUEUE_MAX = 12
# Video frames are fresh allocations, so how many may sit in the decoder's own
# queue is bounded by bytes rather than by a frame count.
VIDEO_QUEUED_BYTES = 3 * 1024 * 1024
VIDEO_STALL_SECONDS = 10.0
VIDEO_CHANNEL_COUNT = 3


@dataclass(frozen=True)
class GpuFrame:
    """Display-ready pixels prepared off the UI thread and reused across repeats.

    `mode` is "RGBA" for animation frames (transparency is preserved) and "RGB"
    for opaque video, so no frame pays for a channel it does not need.
    """
    size: tuple
    pixels: bytes
    mode: str = "RGBA"

    @property
    def width(self):
        return self.size[0]

    @property
    def height(self):
        return self.size[1]

    def tobytes(self):
        return self.pixels

    def image(self):
        """A PIL view sharing this frame's immutable bytes; no pixel copy."""
        return Image.frombuffer(self.mode, self.size, self.pixels, "raw", self.mode, 0, 1)

    def convert(self, mode):
        return self.image().convert(mode)

    @classmethod
    def from_image(cls, image, mode=None, size=None):
        return freeze(image, size=size, mode=mode or "RGBA")


def freeze(source, size=None, mode="RGBA"):
    """One decoded frame as immutable bytes, with no redundant channel pass.

    An already-correct mode is copied straight to bytes; only a mismatched mode
    pays for a conversion, and only an oversized frame pays for a resize.
    """
    width, height = source.size
    resized = size is not None and (width > size[0] or height > size[1])
    if source.mode == mode and not resized:
        return GpuFrame((width, height), source.tobytes(), mode)
    image = source.copy() if source.mode == mode else source.convert(mode)
    if resized:
        # Bilinear is enough for a downscaled screen copy and costs less than LANCZOS.
        image.thumbnail(size, Image.Resampling.BILINEAR)
    return GpuFrame(image.size, image.tobytes(), image.mode)


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
        # next() can leave the index past the end of a finished non-looping
        # playlist; clamp before indexing so backward navigation never crashes.
        if not self.cycle:
            return None
        self.index = min(max(0, self.index - 1), len(self.cycle) - 1)
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
    """Deadline-based frame pacing on a monotonic clock.

    A frame's deadline advances by the media's own duration, never by how long
    decoding or presentation took, so playback neither drifts nor slows down.
    """

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
        return self.deadline

    def due(self):
        """True once the armed deadline has passed."""
        return self.deadline is not None and self.now() >= self.deadline

    def late(self):
        """True when the armed window is already over, so this frame is stale."""
        return self.deadline is not None and self.now() >= self.deadline

    def ready(self):
        return not self.paused and (self.deadline is None or self.now() >= self.deadline)

    def delay_ms(self):
        # Paused playback and an unarmed clock only need a coarse heartbeat; a
        # running clock waits exactly for its deadline, capped so a long still
        # image or video frame does not keep the Tk event loop awake at frame
        # rate for the whole duration.
        if self.paused:
            return 250
        if self.deadline is None:
            return 10
        return max(1, min(250, math.ceil((self.deadline - self.now()) * 1000)))

    def lag(self):
        """Seconds late against the media timeline; zero when on time."""
        if self.deadline is None or self.paused:
            return 0.0
        return max(0.0, self.now() - self.deadline)

    def resync(self, seconds=0.0):
        """Accept reality after dropping frames instead of drifting forever."""
        self.deadline = self.now() + max(0.0, seconds)
        self.remaining = max(0.0, seconds)

    def toggle(self):
        if self.deadline is not None:
            if self.paused:
                self.deadline = self.now() + self.remaining
            else:
                self.remaining = max(0, self.deadline - self.now())
        self.paused = not self.paused


def gif_seconds(value):
    if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        return 0.1
    return max(0.02, min(10, value / 1000))


def drain(channel):
    while True:
        try:
            channel.get_nowait()
        except queue.Empty:
            return


class VideoStream:
    """A persistent muted FFmpeg decode with its own bounded decoded-frame queue.

    One process serves every repeat, the reader thread keeps the pipe drained so
    FFmpeg is never blocked by presentation, and no frame is ever decoded twice.
    Audio and subtitle streams are never decoded.
    """

    def __init__(self, processes, stream, size, fps, repeats=1, hwaccel=None, loop=False,
                 stall=VIDEO_STALL_SECONDS):
        self.processes = processes
        self.stream = stream
        self.size = (max(1, int(size[0])), max(1, int(size[1])))
        self.frame_bytes = self.size[0] * self.size[1] * VIDEO_CHANNEL_COUNT
        self.fps = playback_fps(fps)
        self.seconds = 1.0 / self.fps
        self.repeats = max(1, int(repeats))
        self.hwaccel = hwaccel
        self.loop = bool(loop)
        self.stall = float(stall)
        self.depth = max(1, min(VIDEO_QUEUE_MAX, VIDEO_QUEUE_BYTES // max(1, self.frame_bytes)))
        self.ahead = max(1, VIDEO_QUEUED_BYTES // max(1, self.frame_bytes))
        self.queue = queue.Queue(maxsize=self.depth)
        self.cancel = threading.Event()
        self.process = None
        self.thread = None
        self.failure = None
        self.produced = 0
        self.started = False

    def start(self):
        if self.started:
            raise RuntimeError("VideoStream already started")
        self.started = True
        stream = self.stream
        stream.seek(0)
        command = video_command(stream.fileno(), self.size, self.fps, self.hwaccel,
                                loop=self.loop) + ["-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
        self.process = self.processes.start(command, pass_fds=(stream.fileno(),),
                                           stdout=subprocess.PIPE, bufsize=0)
        self.thread = threading.Thread(target=self._read, name="carousel-video-read")
        self.thread.start()
        return self

    def _offer(self, payload):
        """Bounded hand-off that stays interruptible while the queue is full."""
        while not self.cancel.is_set():
            try:
                self.queue.put(payload, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _read(self):
        fd = self.process.stdout.fileno()
        frame = bytearray(self.frame_bytes)
        view = memoryview(frame)
        filled = 0
        deadline = time.monotonic() + self.stall
        try:
            while not self.cancel.is_set():
                if not select.select([fd], [], [], 0.2)[0]:
                    if time.monotonic() > deadline:
                        self._fail("WebM decoder stalled")
                        return
                    continue
                chunk = os.read(fd, self.frame_bytes - filled)
                if not chunk:
                    if filled:
                        self._fail("WebM decoder found corrupt video")
                    return
                view[filled:filled + len(chunk)] = chunk
                filled += len(chunk)
                deadline = time.monotonic() + self.stall
                if filled == self.frame_bytes:
                    filled = 0
                    self.produced += 1
                    if not self._offer(("frame", bytes(frame))):
                        return
        except (OSError, ValueError):
            if not self.cancel.is_set():
                self._fail("WebM decoder pipe failed")
        finally:
            # The end marker must always be offered, and reaping must never be
            # able to strand the consumer with no frame and no terminal event.
            view.release()
            try:
                self._reap()
            finally:
                self._offer(("end", None))

    def _fail(self, message):
        self.failure = MediaError(message)
        self._offer(("error", message))

    def _reap(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdout.close()
        except (OSError, AttributeError):
            pass
        try:
            self.processes.finish(process)
        except OSError:
            # A process that is already gone cannot be reaped twice; the reader
            # must still reach its end marker.
            pass

    def frames(self):
        """Yield raw RGB frames until the stream ends, fails or is cancelled."""
        if not self.started:
            self.start()
        while not self.cancel.is_set():
            try:
                kind, payload = self.queue.get(timeout=0.1)
            except queue.Empty:
                if self.failure is not None:
                    raise self.failure
                continue
            if kind == "frame":
                yield payload
            elif kind == "error":
                raise MediaError(payload)
            else:
                if self.failure is not None:
                    raise self.failure
                return

    def abort(self):
        """Signal and kill now; the reader thread reaps and closes the pipe."""
        self.cancel.set()
        process = self.process
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    def close(self):
        self.abort()
        thread, self.thread = self.thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
            if thread.is_alive():
                raise RuntimeError("Video reader did not stop within 3 seconds")
        self._reap()


class Decoder:
    def __init__(self, library):
        self.library = library
        self.commands = queue.Queue(maxsize=1)
        self.events = queue.Queue(maxsize=LOOKAHEAD + 2)
        self.closed = threading.Event()
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.processes = Processes()
        self.video = None
        self.generation = 0
        self.animation_cache = AnimationCache(self._prepare_animation, lambda: MAX_ANIMATION_BYTES)
        self.still_lock = threading.Lock()
        self.still_cache = OrderedDict()
        self.still_bytes = 0
        self.thread = threading.Thread(target=self._work, name="carousel-decoder")
        self.thread.start()

    # ---- lifecycle ------------------------------------------------------

    def stop(self, clear_cache=True):
        with self.lock:
            self.generation += 1
            self.cancel.set()
            video, self.video = self.video, None
        if video is not None:
            video.abort()
        drain(self.commands)
        drain(self.events)
        if clear_cache:
            self.animation_cache.clear()
            self._clear_stills()

    def close(self):
        self.closed.set()
        self.stop()
        self.animation_cache.close()
        self.processes.close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("Decoder worker did not stop within 3 seconds")

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

    # ---- producer -------------------------------------------------------

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
                        self._video(stream, size, settings, cancel, generation, item)
                    else:
                        self._image(stream, size, settings, cancel, generation, item)
                self._emit(cancel, generation, "done")
            except DetectionCancelled:
                # Navigation or shutdown withdrew the probe; nothing to report.
                continue
            except (OSError, ValueError, EOFError, SyntaxError, subprocess.SubprocessError,
                    Image.DecompressionBombError) as error:
                message = str(error) if isinstance(error, MediaError) else "File missing, corrupt or no longer readable"
                self._emit(cancel, generation, "error", message)
            except Exception as error:
                # The worker must never die silently: an unexpected failure still
                # terminates this generation so playback can skip the item.
                self._emit(cancel, generation, "error",
                           "Media could not be decoded (" + type(error).__name__ + ")")

    # ---- still images ---------------------------------------------------

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
        weight = len(image.pixels)
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
            oriented = ImageOps.exif_transpose(source)
            still = freeze(oriented, size=size, mode="RGBA")
            self._still_store(item, size, still)
            self._emit(cancel, generation, "frame", still, settings["image_seconds"])

    # ---- animations -----------------------------------------------------

    def _animation(self, source, size, settings, cancel, generation, item):
        if source.width * source.height > MAX_GIF_PIXELS:
            raise MediaError("Animation frame exceeds pixel limit")
        gpu = bool(settings.get("gpu"))
        prepared = self.animation_cache.take(item, size, gpu)
        if prepared:
            for _ in range(settings["repeats"]):
                for frame, seconds in prepared:
                    if not self._emit(cancel, generation, "frame", frame, seconds):
                        return
                if cancel.is_set():
                    return
            return
        # Stream the first pass so the first frame appears immediately, and record
        # it for the repeats that follow and for the next visit to this item.
        recorded, used, keep = [], 0, True
        limit = self.animation_cache.budget()
        self.animation_cache.foreground_busy(True)
        try:
            for repeat in range(settings["repeats"]):
                if cancel.is_set() or self.closed.is_set():
                    return
                if repeat and keep:
                    for frame, seconds in recorded:
                        if not self._emit(cancel, generation, "frame", frame, seconds):
                            return
                    continue
                source.seek(0)
                for frame, seconds in self._animation_frames(source, size, gpu, cancel):
                    if keep:
                        used += len(frame.pixels)
                        if used > limit:
                            keep, recorded = False, []
                        else:
                            recorded.append((frame, seconds))
                    if not self._emit(cancel, generation, "frame", frame, seconds):
                        return
        finally:
            self.animation_cache.foreground_busy(False)
        if keep and recorded:
            self.animation_cache.store(item, size, gpu, recorded, used)
        elif not keep:
            self.animation_cache.skip(item, size, gpu)

    def _animation_frames(self, source, size, gpu, cancel, deadline=None):
        """Yield (frame, seconds) forward through GIF or animated WebP frames."""
        frames, pixels = 0, 0
        while not cancel.is_set() and not self.closed.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                raise MediaError("Animation exceeds frame/decode budget")
            if source.width * source.height > MAX_GIF_PIXELS:
                raise MediaError("Animation frame exceeds pixel limit")
            # Read pixels first: WebP reports the previous frame's duration until
            # the current frame is loaded. Pillow composites disposal and
            # transparency into every frame it hands back.
            frame = freeze(source, size=None if gpu else size, mode="RGBA")
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

    # ---- video ----------------------------------------------------------

    def _video(self, stream, size, settings, cancel, generation, item):
        details = video_details(stream, (item["id"], item["size"]))
        fps = playback_fps(details.get("fps"))
        seconds = 1.0 / fps
        repeats = max(1, int(settings["repeats"]))
        budget = max(1, int(round(float(details.get("duration", 0)) * fps))) * repeats
        budget = min(budget, int(MAX_VIDEO_SECONDS * MAX_VIDEO_FPS) + 1)
        backend = video_backend(details.get("codec"), cancel=cancel)
        self._report_decoder(details.get("codec"), backend)
        candidates = [backend['method']] if backend['verified'] else [None]
        if backend['verified']:
            candidates.append(None)  # A file this particular decoder rejects still plays.
        error = None
        for index, method in enumerate(candidates):
            video = VideoStream(self.processes, stream, size, fps, repeats,
                                hwaccel=method, loop=repeats > 1)
            with self.lock:
                self.video = video
            try:
                emitted = self._pump_video(video, size, seconds, budget, cancel, generation)
                if emitted or index == len(candidates) - 1:
                    return
                error = MediaError("Video decoder produced no frames")
            except MediaError as failure:
                error = failure
                if index == len(candidates) - 1:
                    raise
            finally:
                try:
                    video.close()
                finally:
                    with self.lock:
                        if self.video is video:
                            self.video = None
            if cancel.is_set() or self.closed.is_set():
                return
            self._report_decoder(details.get("codec"), dict(backend, name='software', method=None,
                                                             verified=False, reason=str(error)))
        if error is not None and not cancel.is_set():
            raise error

    def _pump_video(self, video, size, seconds, budget, cancel, generation):
        emitted = 0
        for raw in video.frames():
            if cancel.is_set() or self.closed.is_set():
                return emitted
            emitted += 1
            if emitted > budget:
                return emitted
            # Keep only a byte-bounded look-ahead queued for presentation, so a
            # large window cannot multiply buffered pixels behind the screen.
            while self.events.qsize() >= video.ahead:
                if cancel.is_set() or self.closed.is_set():
                    return emitted
                cancel.wait(0.01)
            if not self._emit(cancel, generation, "frame", GpuFrame(size, raw, "RGB"), seconds):
                return emitted
        return emitted

    @staticmethod
    def _report_decoder(codec, backend):
        print("event=video_decoder codec=%s backend=%s hwaccel=%r verified=%s reason=%r"
              % (codec, backend.get('name'), backend.get('method'), backend.get('verified'),
                 backend.get('reason')), file=sys.stderr)
