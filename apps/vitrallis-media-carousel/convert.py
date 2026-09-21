"""On-device GIF to animated WebP conversion through gif2webp or Pillow."""
import math
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from PIL import Image

from media import MAX_ANIMATION_PIXELS, MAX_FRAMES


HEADROOM = 8 * 1024 * 1024
POLL = 0.1
DEADLINE = 300
TAIL_BYTES = 400
MESSAGE_CHARS = 200
FALLBACK_PIXEL_BUDGET = 32_000_000


class ConversionError(ValueError):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class _Cancelled(Exception):
    pass


def converter_available():
    return shutil.which("gif2webp")


def converted_name(name):
    stem = name[:-4] if name[-4:].lower() == ".gif" else name
    return stem[:155] + ".webp"


def _delay(value):
    """GIF delays at or below zero use the 100 ms viewer convention, like playback
    and gif2webp, so a converted animation keeps its effective timing."""
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return 100
    return int(round(value))


def _tail(raw):
    return raw.decode("utf-8", "replace").strip()[-TAIL_BYTES:]


def _bounded(message):
    return str(message)[:MESSAGE_CHARS]


class Conversions:
    """One conversion job at a time; the source GIF survives every failure path."""

    def __init__(self, library, processes):
        self.library = library
        self.processes = processes
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.closed = False
        self.cancel = threading.Event()
        self.thread = None
        self.process = None
        self.state = {"status": "idle", "message": "", "item": None, "replacement": None,
                      "name": "", "collection": None, "converter": ""}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, cid, mid):
        items = self.library.playlist(cid)
        item = next((row for row in items if row["id"] == mid), None)
        if item is None:
            raise KeyError("Media no longer exists")
        if item["kind"] != "gif":
            raise ConversionError("Only GIF animations can be converted")
        if shutil.disk_usage(self.library.paths.uploads).free < item["size"] + HEADROOM:
            raise ConversionError("Not enough free space to convert this animation")
        name = converted_name(item["name"])
        with self.lock:
            if self.closed:
                raise RuntimeError("Conversions is closed")
            if (self.state["status"] == "running" and self.thread is not None
                    and self.thread.is_alive()):
                raise ConversionError("A conversion is already running", code=409)
            self.cancel = threading.Event()
            self.state.update(status="running", message="Reading…", item=item["id"],
                              replacement=None, name=name, collection=cid,
                              converter="gif2webp" if converter_available() else "pillow")
            self.thread = threading.Thread(target=self._run, name="carousel-conversion",
                                           args=(cid, dict(item), name, self.state["converter"]))
            self.thread.start()
        return self.snapshot()

    def close(self):
        with self.lock:
            self.closed = True
            self.cancel.set()
            thread, process = self.thread, self.process
        if process is not None:
            self.processes.finish(process)
        if thread is not None:
            thread.join(timeout=3)
            if thread.is_alive():
                raise RuntimeError("Conversion worker did not stop within 3 seconds")

    def _message(self, message):
        with self.lock:
            self.state["message"] = message

    def _finish(self, status, message, replacement=None):
        with self.condition:
            self.state.update(status=status, message=message, replacement=replacement)
            self.condition.notify_all()

    def _check_cancel(self):
        if self.cancel.is_set():
            raise _Cancelled()

    def _run(self, cid, item, name, converter):
        staged = None
        outcome = ("failed", "Conversion failed; the original GIF is unchanged", None)
        try:
            staged = self._stage()
            self._check_cancel()
            self._message("Reading…")
            with self.library.open_item(item) as source:
                if os.fstat(source.fileno()).st_size != item["size"]:
                    raise ConversionError("Media size no longer matches the library")
                details = self._read_source(source)
                self._check_cancel()
                self._message("Converting… (%d frames)" % details["frames"])
                if converter == "gif2webp":
                    self._convert_gif2webp(source, staged)
                else:
                    self._convert_pillow(source, staged, details)
                self._check_cancel()
                self._message("Verifying…")
                info = self._verify(staged, details)
            self._check_cancel()
            replacement = self.library.replace_upload(cid, item["id"], name, staged, info)
            outcome = ("ready", "Converted to WebP", replacement["id"])
        except _Cancelled:
            outcome = ("idle", "Conversion cancelled", None)
        except (OSError, ValueError, EOFError, SyntaxError, subprocess.SubprocessError,
                Image.DecompressionBombError) as error:
            message = str(error) if isinstance(error, ConversionError) else \
                "Conversion failed; the original GIF is unchanged"
            outcome = ("failed", _bounded(message), None)
        except Exception:
            pass
        finally:
            if staged is not None:
                try:
                    if os.path.lexists(staged):
                        os.unlink(staged)
                except OSError:
                    pass
            self._finish(*outcome)

    def _stage(self):
        fd, path = tempfile.mkstemp(prefix="convert-", dir=self.library.paths.uploads)
        os.close(fd)
        return Path(path)

    def _read_source(self, stream):
        stream.seek(0)
        with Image.open(stream, formats=("GIF",)) as source:
            if source.format != "GIF":
                raise ConversionError("Only GIF animations can be converted")
            frames = int(getattr(source, "n_frames", 1))
            if not 1 <= frames <= MAX_FRAMES:
                raise ConversionError("GIF frame count is outside the supported range")
            durations, pixels = [], 0
            for index in range(frames):
                self._check_cancel()
                source.seek(index)
                source.load()
                durations.append(_delay(source.info.get("duration")))
                pixels += source.width * source.height
                if pixels > MAX_ANIMATION_PIXELS:
                    raise ConversionError("Animation exceeds the conversion pixel budget")
            return {"frames": frames, "loop": source.info.get("loop", 0),
                    "loop_known": "loop" in source.info, "duration_ms": sum(durations)}

    def _convert_gif2webp(self, stream, staged):
        converter = converter_available()
        if converter is None:
            raise ConversionError("gif2webp is unavailable; install the webp package")
        stream.seek(0)
        command = [sys.executable, "-B", str(Path(__file__).resolve()), converter,
                   "-quiet", "-q", "80", "-m", "4", "-metadata", "none",
                   "/dev/fd/" + str(stream.fileno()), "-o", str(staged)]
        process = self.processes.start(command, pass_fds=(stream.fileno(),),
                                       stdout=subprocess.PIPE)
        with self.lock:
            self.process = process
        output = bytearray()
        try:
            deadline = time.monotonic() + DEADLINE
            with process.stdout:
                while True:
                    if self.cancel.is_set():
                        raise _Cancelled()
                    if time.monotonic() >= deadline:
                        raise ConversionError("gif2webp exceeded the 300-second deadline")
                    if not select.select([process.stdout], [], [], POLL)[0]:
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        if process.wait(timeout=1) != 0:
                            tail = _tail(output)
                            raise ConversionError("gif2webp failed: " + tail if tail
                                                  else "gif2webp failed")
                        return
                    output.extend(chunk)
                    if len(output) > TAIL_BYTES * 2:
                        del output[:-TAIL_BYTES]
        finally:
            with self.lock:
                self.process = None
            self.processes.finish(process)

    def _convert_pillow(self, stream, staged, details):
        stream.seek(0)
        frames, durations, pixels = [], [], 0
        try:
            with Image.open(stream, formats=("GIF",)) as source:
                while True:
                    self._check_cancel()
                    # Pillow composites disposal and transparency into each fresh copy.
                    frame = source.convert("RGBA")
                    pixels += frame.width * frame.height
                    if pixels > FALLBACK_PIXEL_BUDGET:
                        raise ConversionError("Animation too large for the built-in converter; "
                                              "install webp/gif2webp")
                    durations.append(_delay(source.info.get("duration")))
                    frames.append(frame)
                    try:
                        source.seek(len(frames))
                    except EOFError:
                        break
            frames[0].save(staged, format="WEBP", save_all=True, append_images=frames[1:],
                           duration=durations, loop=details["loop"], quality=80, method=4)
        finally:
            frames.clear()

    def _verify(self, staged, details):
        with Image.open(staged, formats=("WEBP",)) as result:
            if result.format != "WEBP":
                raise ConversionError("Converter did not produce a WebP file")
            frames = int(getattr(result, "n_frames", 1))
            if frames != details["frames"]:
                raise ConversionError("Converted animation frame count changed")
            loop = result.info.get("loop", 0)
            if frames > 1:
                if not bool(getattr(result, "is_animated", False)):
                    raise ConversionError("Converted animation lost its animation")
                if details["loop_known"]:
                    if details["loop"] == 0 and loop != 0:
                        raise ConversionError("Converted animation lost infinite looping")
                    if details["loop"] != 0 and loop == 0:
                        raise ConversionError("Converted animation lost its loop count")
                durations, pixels = [], 0
                for index in range(frames):
                    self._check_cancel()
                    result.seek(index)
                    result.load()  # WebP reports a frame duration only after loading it.
                    duration = result.info.get("duration")
                    if (not isinstance(duration, (int, float)) or not math.isfinite(duration)
                            or duration < 0):
                        raise ConversionError("Converted animation frame durations are missing")
                    durations.append(int(round(duration)))
                    pixels += result.width * result.height
                    if pixels > MAX_ANIMATION_PIXELS:
                        raise ConversionError("Converted animation exceeds the decode budget")
                if abs(sum(durations) - details["duration_ms"]) > max(50, details["duration_ms"] * .05):
                    raise ConversionError("Converted animation durations changed")
                duration_ms = sum(durations)
            else:
                if bool(getattr(result, "is_animated", False)):
                    raise ConversionError("Converted still image became animated")
                duration_ms = 0
            return {"kind": "webp", "width": result.width, "height": result.height,
                    "frames": frames, "animated": frames > 1, "loop": loop,
                    "duration_ms": duration_ms}


def conversion_main():
    # Applied in this isolated wrapper, never preexec_fn in a threaded application.
    if len(sys.argv) < 2:
        raise SystemExit("usage: convert.py PROGRAM [ARG ...]")
    converter, arguments = sys.argv[1], sys.argv[2:]
    if sys.platform.startswith("linux"):
        import resource
        limit = (512 if sys.maxsize > 2 ** 32 else 256) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    os.dup2(1, 2)  # Keep converter diagnostics on the pipe the parent already reads.
    os.execv(converter, [converter] + arguments)


if __name__ == "__main__":
    conversion_main()
