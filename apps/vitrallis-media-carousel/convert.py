"""Batch GIF and still-image to WebP conversion through gif2webp or Pillow.

Every item is converted through a staged temporary file, verified against the
source's frame count, durations, dimensions, orientation and transparency, and
only then swapped into the library. The original is never touched before that
point, so a failure of any kind leaves the source byte-for-byte unchanged and
removes the staged file.

A job converts many items with a small bounded worker pool rather than a thread
or process per file, reports per-item progress, skips media that is already WebP,
and keeps going when one item fails.
"""
from contextlib import contextmanager
import itertools
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

from PIL import Image, ImageOps

from media import MAX_ANIMATION_PIXELS, MAX_FRAMES, MAX_PIXELS

HEADROOM = 8 * 1024 * 1024
POLL = 0.1
DEADLINE = 300
TAIL_BYTES = 400
MESSAGE_CHARS = 200
FALLBACK_PIXEL_BUDGET = 32_000_000
STILL_QUALITY = 90
STILL_METHOD = 4
RESULT_LIMIT = 500
WORKER_LIMIT = 2

# Kinds this converter can produce WebP from, and the bucket each one belongs to.
GIF_KINDS = ("gif",)
IMAGE_KINDS = ("png", "jpeg")
WEBP_KIND = "webp"
SKIPPED_KINDS = ("webm",)
STILL_EXTENSIONS = (".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".tif", ".tiff")
BUCKETS = ("gif", "image")

JOB_IDLE = "idle"
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"


class ConversionError(ValueError):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class _Cancelled(Exception):
    pass


def converter_available():
    return shutil.which("gif2webp")


def worker_count():
    """A small, explicit pool: one worker unless the host has cores to spare."""
    override = os.environ.get("CAROUSEL_CONVERT_WORKERS")
    if override and override.isdigit():
        return max(1, min(WORKER_LIMIT, int(override)))
    return 2 if (os.cpu_count() or 1) >= 4 else 1


def converted_name(name):
    """Replace a convertible extension, never re-adding one that is already there."""
    lowered = name.casefold()
    for suffix in (".gif", *STILL_EXTENSIONS, ".webp"):
        if lowered.endswith(suffix):
            return name[:-len(suffix)][:155] + ".webp"
    return name[:155] + ".webp"


def bucket(item):
    """Which bulk action owns this item; None when it has no WebP target."""
    kind = item.get("kind")
    if kind in GIF_KINDS:
        return "gif"
    if kind in IMAGE_KINDS:
        return "image"
    if kind == WEBP_KIND:
        # Already the target format; an animated WebP is the GIF workflow's result.
        return "gif" if item.get("animated") else "image"
    return None


def needs_conversion(item):
    """True when converting this item would still change anything."""
    return bucket(item) is not None and item.get("kind") != WEBP_KIND


def convertible(item, kinds, replace=False):
    return bucket(item) in kinds


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


def _still_mode(source):
    """WebP output mode that keeps a still image faithful to its source."""
    if source.mode in ("RGBA", "LA", "PA"):
        return "RGBA"
    if source.mode == "P":
        return "RGBA" if "transparency" in source.info else "RGB"
    return "RGB"


class Conversions:
    """One conversion job at a time; the source media survives every failure path."""

    def __init__(self, library, processes, workers=None):
        self.library = library
        self.processes = processes
        self.workers = workers or worker_count()
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.closed = False
        self.cancel = threading.Event()
        self.threads = []
        self.children = set()
        self.jobs = itertools.count(1)
        self.job = self._idle_job()
        self.item = self._idle_item()
        self.last = None

    # ---- snapshots ------------------------------------------------------

    @staticmethod
    def _idle_job():
        return {"id": 0, "status": JOB_IDLE, "scope": "collection", "collection": None,
                "scope_name": "", "all": False, "kinds": [], "replace": False,
                "total": 0, "completed": 0, "failed": 0, "skipped": 0, "current": "",
                "message": "", "converter": "", "started": 0.0, "finished": 0.0,
                "results": [], "truncated": 0, "workers": 0}

    @staticmethod
    def _idle_item():
        return {"status": JOB_IDLE, "message": "", "item": None, "replacement": None,
                "name": "", "collection": None, "converter": ""}

    def snapshot(self):
        with self.lock:
            value = dict(self.item)
            value["job"] = dict(self.job, results=list(self.job["results"]))
            return value

    # ---- job control ----------------------------------------------------

    def _running(self):
        return any(thread.is_alive() for thread in self.threads)

    def start(self, cid, mid):
        """Convert one library item; keeps the original single-item contract."""
        items = self.library.playlist(cid)
        item = next((row for row in items if row["id"] == mid), None)
        if item is None:
            raise KeyError("Media no longer exists")
        if not needs_conversion(item):
            raise ConversionError("Only GIF animations and PNG/JPEG images can be converted")
        return self._launch("collection", cid, [(cid, item)], [bucket(item)], replace=False)

    def start_bulk(self, scope, kinds, replace=False, collection=None):
        """Queue every matching item in one collection, or in the whole library."""
        kinds = [name for name in BUCKETS if name in kinds]
        if not kinds:
            raise ConversionError("Choose GIFs, images or both")
        with self.library.lock:
            rows = self.library.snapshot()
        if scope == "all":
            selected = [(row["id"], item) for row in rows for item in row["items"]]
            scope_name = "All collections"
        else:
            row = next((row for row in rows if row["id"] == collection), None)
            if row is None:
                raise KeyError("Collection no longer exists")
            selected = [(row["id"], item) for item in row["items"]]
            scope_name = row["name"]
        candidates = [(cid, item) for cid, item in selected
                      if bucket(item) in kinds and item["kind"] not in SKIPPED_KINDS]
        if not candidates:
            raise ConversionError("Nothing to convert; no matching GIF or still image here")
        return self._launch(scope, collection, candidates, kinds, replace, scope_name)

    def _launch(self, scope, collection, candidates, kinds, replace, scope_name=""):
        """Start one bounded conversion job over an already-planned item list.

        Candidates already in WebP stay in the plan so the job can report them as
        skipped instead of silently reconverting or silently ignoring them.
        """
        candidates = [(cid, dict(item)) for cid, item in candidates]
        work = [entry for entry in candidates if replace or needs_conversion(entry[1])]
        with self.condition:
            if self.closed:
                raise RuntimeError("Conversions is closed")
            if self._running():
                raise ConversionError("A conversion is already running", code=409)
            short = [item["name"] for _, item in work
                     if shutil.disk_usage(self.library.paths.uploads).free < item["size"] + HEADROOM]
            if short:
                raise ConversionError("Not enough free space to convert %s" % short[0])
            self.cancel = threading.Event()
            self.job = dict(self._idle_job(), id=next(self.jobs), status=JOB_QUEUED, scope=scope,
                            collection=collection, scope_name=scope_name, all=scope == "all",
                            kinds=list(kinds), replace=bool(replace), total=len(candidates),
                            converter="gif2webp" if converter_available() else "pillow",
                            workers=min(self.workers, len(work)) or 1, started=time.time())
            first = candidates[0][1]
            self.item = dict(self._idle_item(), status=JOB_RUNNING,
                             message="Converting %s" % _bounded(first["name"]),
                             item=first["id"], name=converted_name(first["name"]),
                             collection=candidates[0][0], converter=self.job["converter"])
            coordinator = threading.Thread(target=self._work, name="carousel-conversion",
                                           args=(self.cancel, candidates))
            self.threads = [coordinator]
            coordinator.start()
        return self.snapshot()

    def request_cancel(self):
        """Request cancellation; workers stop before publishing anything."""
        with self.lock:
            self.cancel.set()
            children = list(self.children)
        for process in children:
            self.processes.finish(process)

    def close(self):
        with self.lock:
            self.closed = True
            self.cancel.set()
            threads, children = list(self.threads), list(self.children)
        for process in children:
            self.processes.finish(process)
        deadline = time.monotonic() + 5
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("Conversion worker did not stop within 5 seconds")

    # ---- internal publication ------------------------------------------

    def _message(self, message):
        with self.lock:
            self.item["message"] = message

    def _publish_item(self, cid, item, name, status, message, replacement=None):
        with self.condition:
            self.item = {"status": status, "message": message, "item": item["id"],
                         "replacement": replacement, "name": name, "collection": cid,
                         "converter": self.job["converter"]}
            self.condition.notify_all()

    def _record(self, cid, item, status, message, replacement=None, name=None):
        name = name or converted_name(item["name"])
        with self.condition:
            if len(self.job["results"]) < RESULT_LIMIT:
                self.job["results"].append(
                    {"item": item["id"], "name": item["name"], "collection": cid,
                     "kind": item["kind"], "status": status, "message": message})
            else:
                self.job["truncated"] += 1
            if status == "converted":
                self.job["completed"] += 1
            elif status == "skipped":
                self.job["skipped"] += 1
            else:
                self.job["failed"] += 1
            self.job["current"] = item["name"]
            self.last = {"item": item["id"], "replacement": replacement, "name": name,
                         "collection": cid, "status": status, "message": message}
            if self.job["total"] <= 1:
                # The single-item view keeps the classic shape the native UI reads.
                self._publish_item(cid, item, name, JOB_RUNNING, message, replacement)
            self.condition.notify_all()

    def _finish_job(self, status, message):
        """Publish the batch outcome and the flat view the native UI polls."""
        with self.condition:
            self.job["status"] = status
            self.job["message"] = message
            self.job["finished"] = time.time()
            if status == JOB_CANCELLED:
                item_status = "idle"
            elif status == JOB_FAILED:
                item_status = "failed"
            else:
                item_status = "ready"
            if self.job["total"] <= 1 and self.last:
                self.item = {"status": item_status,
                             "message": "Converted to WebP" if status == JOB_COMPLETED
                             else self.last["message"],
                             "item": self.last["item"], "replacement": self.last["replacement"],
                             "name": self.last["name"], "collection": self.last["collection"],
                             "converter": self.job["converter"]}
            else:
                self.item = dict(self.item, status=item_status, message=message,
                                 replacement=self.last["replacement"] if self.last else None)
            self.condition.notify_all()

    def _check_cancel(self):
        if self.cancel.is_set():
            raise _Cancelled()

    # ---- the job -------------------------------------------------------

    def _work(self, cancel, plan):
        """Coordinate a bounded pool of per-item workers until the plan is done."""
        with self.condition:
            self.job["status"] = JOB_RUNNING
            self.condition.notify_all()
        cursor, cursor_lock = itertools.count(), threading.Lock()

        def take():
            with cursor_lock:
                return next(cursor)

        workers = [threading.Thread(target=self._drain, name="carousel-conversion-item",
                                    args=(cancel, plan, take))
                   for _ in range(max(1, min(self.workers, len(plan))))]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        with self.condition:
            completed, failed, skipped = (self.job["completed"], self.job["failed"],
                                          self.job["skipped"])
            if cancel.is_set():
                self._finish_job(JOB_CANCELLED, "Conversion cancelled")
            elif completed == 0 and failed:
                self._finish_job(JOB_FAILED, "Conversion failed for every item")
            else:
                self._finish_job(JOB_COMPLETED, self._summary(completed, failed, skipped))

    @staticmethod
    def _summary(completed, failed, skipped):
        parts = ["Converted %d" % completed]
        if failed:
            parts.append("%d failed" % failed)
        if skipped:
            parts.append("%d already WebP" % skipped)
        return " · ".join(parts)

    def _drain(self, cancel, plan, take):
        while not cancel.is_set():
            try:
                number = take()
            except StopIteration:
                return
            if number >= len(plan):
                return
            cid, item = plan[number]
            if cancel.is_set():
                return
            self._convert_one(cancel, cid, item, converted_name(item["name"]))

    def _convert_one(self, cancel, cid, item, name):
        if not (self.job["replace"] or needs_conversion(item)):
            self._record(cid, item, "skipped", "Already WebP", None, name)
            return
        staged = None
        try:
            staged = self._stage()
            self._check_cancel()
            self._publish_item(cid, item, name, JOB_RUNNING,
                               "Converting %s" % _bounded(item["name"]))
            with self.library.open_item(item) as source:
                if os.fstat(source.fileno()).st_size != item["size"]:
                    raise ConversionError("Media size no longer matches the library")
                if bucket(item) == "gif":
                    details = self._convert_animation(source, staged)
                else:
                    details = self._convert_still(source, staged)
                self._check_cancel()
                info = self._verify(staged, details)
            self._check_cancel()
            replacement = self.library.replace_upload(cid, item["id"], name, staged, info)
            self._record(cid, item, "converted", "Converted to WebP", replacement["id"], name)
        except _Cancelled:
            self._record(cid, item, "cancelled", "Cancelled", None, name)
        except Exception as error:
            self._record(cid, item, "failed", self._failure_message(error, item), None, name)
        finally:
            if staged is not None:
                try:
                    if os.path.lexists(staged):
                        os.unlink(staged)
                except OSError:
                    pass

    @staticmethod
    def _failure_message(error, item):
        if isinstance(error, ConversionError):
            return _bounded(error)
        if isinstance(error, (OSError, ValueError, EOFError, SyntaxError,
                              subprocess.SubprocessError, Image.DecompressionBombError)):
            return _bounded("%s could not be converted; the original is unchanged" % item["name"])
        return _bounded("Unexpected conversion failure; the original is unchanged")

    # ---- per-format conversion -----------------------------------------

    def _convert_animation(self, stream, staged):
        details = self._read_source(stream)
        self._check_cancel()
        self._message("Converting… (%d frames)" % details["frames"])
        # gif2webp only understands GIF; an animated WebP is re-encoded in process.
        converter = converter_available() if details.get("source") == "GIF" else None
        if converter:
            self._convert_gif2webp(stream, staged, converter)
        else:
            self._convert_pillow(stream, staged, details)
        return details

    def _convert_still(self, stream, staged):
        details = self._read_still(stream)
        self._check_cancel()
        self._message("Converting… (still image)")
        self._convert_pillow_still(stream, staged, details)
        return details

    def _stage(self):
        fd, path = tempfile.mkstemp(prefix="convert-", dir=self.library.paths.uploads)
        os.close(fd)
        return Path(path)

    def _read_source(self, stream):
        """Frame count and per-frame durations, decoding pixels only when needed."""
        stream.seek(0)
        with Image.open(stream, formats=("GIF", "WEBP")) as source:
            kind = source.format
            if kind not in ("GIF", "WEBP"):
                raise ConversionError("Only GIF and animated WebP can convert as animations")
            frames = int(getattr(source, "n_frames", 1))
            if not 1 <= frames <= MAX_FRAMES:
                raise ConversionError("Animation frame count is outside the supported range")
            durations, pixels = [], 0
            for index in range(frames):
                self._check_cancel()
                source.seek(index)
                if kind == "WEBP":
                    source.load()  # WebP reports a frame duration only after loading it.
                durations.append(_delay(source.info.get("duration")))
                pixels += source.width * source.height
                if pixels > MAX_ANIMATION_PIXELS:
                    raise ConversionError("Animation exceeds the conversion pixel budget")
            if kind == "GIF" and frames > 1:
                # One decoded frame proves the container actually decodes; GIF keeps
                # its durations in the frame headers, so the rest stays undecoded.
                source.seek(0)
                source.load()
            return {"frames": frames, "loop": source.info.get("loop", 0),
                    "loop_known": "loop" in source.info, "duration_ms": sum(durations),
                    "source": kind, "still": frames == 1}

    def _read_still(self, stream):
        stream.seek(0)
        with Image.open(stream) as source:
            if source.format not in ("PNG", "JPEG", "GIF", "WEBP"):
                raise ConversionError("Only PNG, JPEG and GIF images can be converted")
            width, height = source.size
            if width * height > MAX_PIXELS:
                raise ConversionError("Image exceeds the pixel limit")
            if bool(getattr(source, "is_animated", False)):
                raise ConversionError("Animated media must be converted as an animation")
            return {"width": width, "height": height, "mode": _still_mode(source),
                    "format": source.format, "frames": 1, "still": True}

    @contextmanager
    def _child(self, args, fd):
        """Run one isolated converter process and always reap it."""
        process = self.processes.start(args, pass_fds=(fd,), stdout=subprocess.PIPE, bufsize=0)
        with self.lock:
            self.children.add(process)
        try:
            yield process
        finally:
            with self.lock:
                self.children.discard(process)
            self.processes.finish(process)

    def _read_child_output(self, process):
        """Drain a converter's diagnostics, keeping a bounded tail."""
        output = bytearray()
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

    def _convert_gif2webp(self, stream, staged, converter=None):
        converter = converter or converter_available()
        if converter is None:
            raise ConversionError("gif2webp is unavailable; install the webp package")
        stream.seek(0)
        command = [sys.executable, "-B", str(Path(__file__).resolve()), converter,
                   "-quiet", "-q", "80", "-m", "4", "-metadata", "none",
                   "/dev/fd/" + str(stream.fileno()), "-o", str(staged)]
        with self._child(command, stream.fileno()) as process:
            self._read_child_output(process)

    def _convert_pillow(self, stream, staged, details):
        stream.seek(0)
        frames, durations, pixels = [], [], 0
        try:
            with Image.open(stream, formats=("GIF", "WEBP")) as source:
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

    def _convert_pillow_still(self, stream, staged, details):
        stream.seek(0)
        with Image.open(stream) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source) or source
            mode = _still_mode(source)
            image = oriented if oriented.mode == mode else oriented.convert(mode)
            image.save(staged, format="WEBP", quality=STILL_QUALITY, method=STILL_METHOD)

    # ---- verification ---------------------------------------------------

    def _verify(self, staged, details):
        if details.get("still"):
            return self._verify_still(staged, details)
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

    def _verify_still(self, staged, details):
        with Image.open(staged, formats=("WEBP",)) as result:
            if result.format != "WEBP":
                raise ConversionError("Converter did not produce a WebP file")
            if bool(getattr(result, "is_animated", False)):
                raise ConversionError("Converted still image became animated")
            if result.size != (details["width"], details["height"]):
                raise ConversionError("Converted image dimensions changed")
            result.load()
            if details["mode"] == "RGBA" and "A" not in result.mode:
                raise ConversionError("Converted image lost its transparency")
            return {"kind": "webp", "width": result.width, "height": result.height,
                    "frames": 1, "animated": False, "loop": 0, "duration_ms": 0}


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
