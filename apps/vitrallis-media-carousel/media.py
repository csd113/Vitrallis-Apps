"""Bounded media inspection and local-only, muted FFmpeg decoding."""
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
FORMATS = ("PNG", "JPEG", "WEBP", "GIF")


class MediaError(ValueError):
    pass


from multimedia import capabilities


def terminate(process):
    """All app-owned subprocesses start a new session; include their children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=1)


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


def video_info(stream):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MediaError("WebM unavailable: install system ffmpeg and ffprobe")
    stream.seek(0)
    args = [shutil.which("ffprobe"), "-v", "error", "-threads", "1", "-protocol_whitelist", "file,pipe",
            "-f", "matroska,webm", "-select_streams", "v:0", "-show_entries",
            "stream=codec_name,width,height:format=duration", "-of", "json",
            "/dev/fd/" + str(stream.fileno())]
    result = subprocess.run(args, pass_fds=(stream.fileno(),), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
                            check=False)
    if result.returncode or len(result.stdout) > 4096:
        raise MediaError("WebM could not be inspected")
    try:
        data = json.loads(result.stdout)
        video = data["streams"][0]
        width, height = video["width"], video["height"]
        duration = float(data["format"]["duration"])
        if (video["codec_name"] not in ("vp8", "vp9", "av1")
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
    return {"kind": "webm", "width": width, "height": height, "duration": duration}


def video_command(fd, size):
    width, height = size
    decoder = shutil.which("ffmpeg")
    if not decoder or not shutil.which("ffprobe"):
        raise MediaError("WebM unavailable: install system ffmpeg and ffprobe")
    return [decoder, "-v", "error", "-nostdin", "-xerror", "-threads", "1",
            "-filter_threads", "1", "-protocol_whitelist", "file,pipe", "-f", "matroska,webm",
            "-i", "/dev/fd/" + str(fd), "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=20",
            "-t", str(MAX_VIDEO_SECONDS), "-threads", "1"]


def inspect_stream(stream):
    if webm_header(stream):
        return video_info(stream)
    stream.seek(0)
    with Image.open(stream, formats=FORMATS) as source:
        width, height = source.size
        if width * height > MAX_PIXELS:
            raise MediaError("Images are limited to 8 million pixels")
        kind = source.format.lower()
        if kind != "gif" and getattr(source, "is_animated", False):
            raise MediaError("Use GIF or WebM for animated media")
        frames, pixels, deadline = 0, 0, time.monotonic() + 25
        while True:
            if kind == "gif" and source.width * source.height > MAX_GIF_PIXELS:
                raise MediaError("GIFs are limited to 1 million pixels per frame")
            source.load()
            frames += 1
            pixels += source.width * source.height
            if (frames > MAX_FRAMES or (kind == "gif" and pixels > MAX_ANIMATION_PIXELS)
                    or time.monotonic() > deadline):
                raise MediaError("Animation exceeds frame or decode budget")
            try:
                source.seek(frames)
            except EOFError:
                break
        return {"kind": kind, "width": width, "height": height, "frames": frames}


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
