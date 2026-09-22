"""Bounded media inspection, cached video metadata and local-only muted FFmpeg decoding."""
from collections import OrderedDict
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from PIL import Image
from storage import regular_open

MAX_UPLOAD = 64 * 1024 * 1024
MAX_PIXELS = 8_000_000
MAX_GIF_PIXELS = 1_000_000
MAX_FRAMES = 1000
MAX_ANIMATION_PIXELS = 256_000_000
MAX_VIDEO_SECONDS = 1800
MAX_VIDEO_FPS = 30
VIDEO_FPS_FALLBACK = 25
FORMATS = ("PNG", "JPEG", "WEBP", "GIF")

# Playback must not re-probe an immutable blob every time it starts. Blobs are
# named by content ID and verified by size, so (id, size) identifies the file.
_PROBE_CACHE = OrderedDict()
_PROBE_CACHE_LIMIT = 128
_PROBE_LOCK = threading.Lock()


class MediaError(ValueError):
    pass



def terminate(process):
    """All app-owned subprocesses start a new session; include their children.

    A child that already exited but has not been reaped yet can answer
    ``killpg`` with EPERM on some platforms (macOS) instead of ESRCH, so the
    signal attempt is best-effort and the reaping wait is what always runs.
    """
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=0.5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        # Bounded: an unkillable child must never take the caller down with it.
        pass


class Processes:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = set()
        self.closed = False

    def start(self, args, **kwargs):
        with self.lock:
            if self.closed:
                raise MediaError("Application is stopping")
            # Distro decoders can link numerical libraries with independent pools.
            environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
            process = subprocess.Popen(args, start_new_session=True,
                                       stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       env=environment, **kwargs)
            self.active.add(process)
            return process

    def finish(self, process):
        # The decode/validation worker and application shutdown can arrive here
        # together. One owner must signal and reap; concurrent Popen.wait calls
        # can consume each other's timeout budget and signal an already-reaped PID.
        with self.lock:
            if process not in self.active:
                return
            terminate(process)
            self.active.remove(process)

    def close(self):
        with self.lock:
            self.closed = True
            active = list(self.active)
        for process in active:
            self.finish(process)


def remember_probe(identity, info):
    """Cache inspection results for an immutable media blob."""
    if not identity or not info:
        return
    with _PROBE_LOCK:
        _PROBE_CACHE[identity] = dict(info)
        _PROBE_CACHE.move_to_end(identity)
        while len(_PROBE_CACHE) > _PROBE_CACHE_LIMIT:
            _PROBE_CACHE.popitem(last=False)


def cached_probe(identity):
    if not identity:
        return None
    with _PROBE_LOCK:
        info = _PROBE_CACHE.get(identity)
        if info is not None:
            _PROBE_CACHE.move_to_end(identity)
            return dict(info)
    return None


def forget_probe(identity):
    with _PROBE_LOCK:
        _PROBE_CACHE.pop(identity, None)


def frame_rate(value):
    """Parse an FFprobe rational frame rate into a usable playback rate."""
    number = None
    try:
        if isinstance(value, (int, float, str)):
            text = str(value)
            if "/" in text:
                numerator, denominator = text.split("/", 1)
                number = float(numerator) / float(denominator)
            else:
                number = float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if number is None or not math.isfinite(number) or number <= 0:
        return None
    return number


def playback_fps(value):
    """Clamp a probed frame rate to something a small screen should present."""
    rate = frame_rate(value)
    if rate is None:
        return float(VIDEO_FPS_FALLBACK)
    return max(1.0, min(float(MAX_VIDEO_FPS), rate))


def probe(path, processes):
    """Decode untrusted uploads outside the HTTP process, with a wall deadline."""
    with regular_open(path, MAX_UPLOAD) as stream:
        process = processes.start([sys.executable, "-B", str(Path(__file__).resolve()),
                                   str(stream.fileno())], pass_fds=(stream.fileno(),),
                                  stdout=subprocess.PIPE)
        try:
            output, _ = process.communicate(timeout=35)
            if process.returncode or len(output) > 4096:
                raise MediaError("Unsupported, corrupt or resource-intensive media")
            data = json.loads(output)
            if "error" in data:
                raise MediaError(data["error"])
            return data
        except subprocess.TimeoutExpired as error:
            raise MediaError("Media validation exceeded 35 seconds") from error
        finally:
            processes.finish(process)


def vint(stream, keep_marker=False):
    raw = stream.read(1)
    if not raw or not raw[0]:
        raise MediaError("Invalid WebM header")
    first, length, mask = raw[0], 1, 0x80
    while not first & mask:
        mask >>= 1
        length += 1
    tail = stream.read(length - 1)
    if len(tail) != length - 1:
        raise MediaError("Truncated WebM header")
    return int.from_bytes(bytes([first if keep_marker else first & (mask - 1)]) + tail, "big")


def webm_header(stream):
    stream.seek(0)
    if stream.read(4) != b"\x1aE\xdf\xa3":
        return False
    size = vint(stream)
    if size > 4096:
        raise MediaError("WebM header too large")
    end = stream.tell() + size
    doctype = None
    while stream.tell() < end:
        key, length = vint(stream, True), vint(stream)
        if stream.tell() + length > end:
            raise MediaError("Invalid WebM header element")
        value = stream.read(length)
        if key == 0x4282:
            doctype = value
    if doctype != b"webm":
        raise MediaError("Only WebM video containers are supported")
    return True


def ffprobe_json(fd, entries, tags=False, timeout=10):
    """Run FFprobe on an already-open descriptor without touching the path."""
    binary = shutil.which("ffprobe")
    if not binary:
        raise MediaError("WebM unavailable: install system ffmpeg and ffprobe")
    args = [binary, "-v", "error", "-threads", "1", "-protocol_whitelist", "file,pipe",
            "-f", "matroska,webm", "-select_streams", "v:0", "-show_entries", entries,
            "-of", "json", "/dev/fd/" + str(fd)]
    result = subprocess.run(args, pass_fds=(fd,), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False)
    if result.returncode or len(result.stdout) > 65536:
        raise MediaError("WebM could not be inspected")
    return json.loads(result.stdout)


def video_info(stream):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MediaError("WebM unavailable: install system ffmpeg and ffprobe")
    stream.seek(0)
    data = ffprobe_json(stream.fileno(),
                        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate:format=duration")
    try:
        video = data["streams"][0]
        width, height = video["width"], video["height"]
        duration = float(data["format"]["duration"])
        codec = video["codec_name"]
        if (codec not in ("vp8", "vp9", "av1")
                or not 1 <= width <= 4096 or not 1 <= height <= 2160
                or not math.isfinite(duration) or not 0 < duration <= MAX_VIDEO_SECONDS):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise MediaError("WebM needs VP8/VP9/AV1, known duration ≤30 min and size ≤4096×2160") from error
    stream.seek(0)
    result = subprocess.run(video_command(stream.fileno(), (64, 64)) + ["-frames:v", "1",
                            "-f", "null", "-"], pass_fds=(stream.fileno(),),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=10, check=False)
    if result.returncode:
        raise MediaError("WebM has no decodable video frame")
    fps = frame_rate(video.get("avg_frame_rate")) or frame_rate(video.get("r_frame_rate"))
    if fps is None or not 1 <= fps <= 240:
        fps = float(VIDEO_FPS_FALLBACK)
    return {"kind": "webm", "width": width, "height": height, "duration": duration,
            "codec": codec, "fps": fps, "animated": True}


def video_details(stream, identity=None):
    """Cached playback metadata for one open video; probes at most once per blob."""
    info = cached_probe(identity)
    if info and info.get("kind") == "webm" and info.get("fps"):
        return info
    stream.seek(0)
    data = ffprobe_json(stream.fileno(),
                        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate:format=duration")
    try:
        video = data["streams"][0]
        duration = float(data["format"]["duration"])
        codec = video["codec_name"]
        width, height = int(video["width"]), int(video["height"])
        if (codec not in ("vp8", "vp9", "av1") or not math.isfinite(duration)
                or not 0 < duration <= MAX_VIDEO_SECONDS):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise MediaError("WebM could not be inspected for playback") from error
    fps = frame_rate(video.get("avg_frame_rate")) or frame_rate(video.get("r_frame_rate"))
    info = {"kind": "webm", "width": width, "height": height, "duration": duration,
            "codec": codec, "fps": fps if fps and 1 <= fps <= 240 else float(VIDEO_FPS_FALLBACK),
            "animated": True}
    remember_probe(identity, info)
    return info


def video_command(fd, size, fps=None, hwaccel=None, loop=False, limit=MAX_VIDEO_SECONDS):
    """Muted, scaled, frame-rate-normalised raw video from an open descriptor.

    `fps` normalises the output to a constant rate so a presentation deadline of
    1/fps per frame reproduces the source duration instead of guessing.
    """
    width, height = size
    decoder = shutil.which("ffmpeg")
    if not decoder or not shutil.which("ffprobe"):
        raise MediaError("WebM unavailable: install system ffmpeg and ffprobe")
    rate = playback_fps(fps)
    command = [decoder, "-v", "error", "-nostdin", "-xerror", "-threads", "1",
               "-filter_threads", "1", "-protocol_whitelist", "file,pipe",
               "-f", "matroska,webm"]
    if hwaccel:
        # Input option: FFmpeg keeps frames in system memory for the filter graph.
        command += ["-hwaccel", hwaccel]
    if loop:
        command += ["-stream_loop", "-1"]
    command += ["-i", "/dev/fd/" + str(fd), "-map", "0:v:0", "-an", "-sn", "-dn",
                "-vf", f"fps={rate:g},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-t", str(limit), "-threads", "1"]
    return command


def inspect_stream(stream):
    if webm_header(stream):
        return video_info(stream)
    stream.seek(0)
    with Image.open(stream, formats=FORMATS) as source:
        width, height = source.size
        if width * height > MAX_PIXELS:
            raise MediaError("Images are limited to 8 million pixels")
        kind = source.format.lower()
        # Animated WebP shares the frame budget that GIF already had; single-frame
        # files of either format keep the ordinary image limits. Formats without a
        # playback path (for example animated PNG) stay rejected.
        is_animated = bool(getattr(source, "is_animated", False))
        if is_animated and kind not in ("gif", "webp"):
            raise MediaError("Use GIF, WebP or WebM for animation")
        animation = kind == "gif" or (kind == "webp" and is_animated)
        frames, pixels, deadline = 0, 0, time.monotonic() + 25
        while True:
            if animation and source.width * source.height > MAX_GIF_PIXELS:
                raise MediaError("Animation frames are limited to 1 million pixels")
            source.load()
            frames += 1
            pixels += source.width * source.height
            if (frames > MAX_FRAMES or (animation and pixels > MAX_ANIMATION_PIXELS)
                    or time.monotonic() > deadline):
                raise MediaError("Animation exceeds frame or decode budget")
            try:
                source.seek(frames)
            except EOFError:
                break
        return {"kind": kind, "width": width, "height": height, "frames": frames,
                "animated": frames > 1}


def inspection_main():
    # Applied in this isolated child, never preexec_fn in a threaded application.
    if sys.platform.startswith("linux"):
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    try:
        with os.fdopen(int(sys.argv[1]), "rb") as stream:
            if sys.platform.startswith("linux"):
                # This is virtual address space, including mapped shared libraries.
                # 64-bit distro FFmpeg needs more mappings than Pillow/ARMv7.
                megabytes = 1024 if sys.maxsize > 2**32 and webm_header(stream) else 256
                limit = megabytes * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            result = inspect_stream(stream)
    except (OSError, ValueError, EOFError, SyntaxError, subprocess.SubprocessError,
            Image.DecompressionBombError) as error:
        result = {"error": str(error) if isinstance(error, MediaError) else "Unsupported or corrupt media"}
    print(json.dumps(result))


if __name__ == "__main__":
    inspection_main()
