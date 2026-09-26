#!/usr/bin/env python3
"""Reproducible local media benchmarks for the Carousel app.

This is not a unit test and is never discovered by ``unittest``: run it
directly. It measures the same public entry points in any checkout, so the
same command can be pointed at an older version of the package to get genuine
before/after numbers.

    python3 tests/bench_media.py                       # this checkout
    python3 tests/bench_media.py --package /tmp/old --json /tmp/old.json

Nothing here contacts a network service, a device, or a PocketCHIP.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import queue
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default=str(ROOT),
                        help="app package directory to benchmark (default: this checkout)")
    parser.add_argument("--json", default="", help="write the results as JSON to this path")
    parser.add_argument("--seconds", type=float, default=3.0,
                        help="playback window for the presentation benchmark")
    parser.add_argument("--repeats", type=int, default=3, help="measurement repetitions")
    parser.add_argument("--keep-fixtures", action="store_true")
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- fixtures

def animation_frames(count=24, size=(320, 180)):
    palette = ((220, 40, 40), (40, 120, 220), (60, 200, 120), (230, 200, 60))
    frames = []
    for index in range(count):
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        band = Image.new("RGBA", (size[0], 24), palette[index % len(palette)] + (255,))
        image.paste(band, (0, (index * 7) % (size[1] - 24)))
        block = Image.new("RGBA", (64, 64), palette[(index + 2) % len(palette)] + (255,))
        image.paste(block, ((index * 13) % (size[0] - 64), (index * 17) % (size[1] - 64)))
        frames.append(image)
    return frames


def build_fixtures(directory):
    global Image
    from PIL import Image as image_module
    Image = image_module
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = {}
    frames = animation_frames()
    fixtures["gif"] = directory / "animation.gif"
    frames[0].save(fixtures["gif"], format="GIF", save_all=True, append_images=frames[1:],
                   duration=40, loop=0, disposal=2)
    fixtures["webp"] = directory / "animation.webp"
    frames[0].save(fixtures["webp"], format="WEBP", save_all=True, append_images=frames[1:],
                   duration=40, loop=0, quality=85, method=4)
    fixtures["still"] = directory / "still.png"
    Image.new("RGB", (1280, 720), (30, 90, 140)).save(fixtures["still"])
    fixtures["photo"] = directory / "photo.jpg"
    noise = Image.frombytes("RGB", (1600, 1200),
                            bytes(random.Random(7).randbytes(1600 * 1200 * 3)))
    noise.save(fixtures["photo"], quality=88, subsampling=0)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        for name, codec in (("vp8", "libvpx"), ("vp9", "libvpx-vp9")):
            target = directory / ("clip-%s.webm" % name)
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=320x180:rate=25:duration=3", "-c:v", codec,
                            "-b:v", "500k", "-pix_fmt", "yuv420p", "-an", "-y", str(target)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           timeout=60)
            fixtures[name] = target
    return fixtures


# --------------------------------------------------------------------------- helpers

def timed(function):
    started = time.perf_counter()
    value = function()
    return time.perf_counter() - started, value


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


class Bench:
    def __init__(self):
        self.results = {}
        self.notes = []

    def record(self, name, value, unit="ms"):
        self.results[name] = {"value": round(value, 3), "unit": unit}

    def note(self, text):
        self.notes.append(text)

    def report(self):
        width = max([len(name) for name in self.results] or [4])
        lines = []
        for name, entry in self.results.items():
            lines.append("  %-*s %10.2f %s" % (width, name, entry["value"], entry["unit"]))
        for note in self.notes:
            lines.append("  note: " + note)
        return "\n".join(lines)


def environment(package):
    import PIL
    from PIL import features
    from multimedia import executable_key
    ffmpeg = executable_key("ffmpeg")
    version = ""
    if ffmpeg:
        try:
            info = subprocess.run([ffmpeg[0], "-hide_banner", "-version"], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=15, check=False, text=True)
            version = (info.stdout or "").splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            version = "unknown"
    return {
        "package": str(package),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "pillow": "%s (libwebp %s)" % (PIL.__version__, features.version("webp")),
        "ffmpeg": version,
        "cpus": os.cpu_count(),
    }


# --------------------------------------------------------------------------- measurements

def measure_capabilities(bench, repeats):
    import multimedia
    samples = []
    for _ in range(repeats):
        elapsed, report = timed(lambda: multimedia.capabilities(refresh=True))
        samples.append(elapsed * 1000)
    bench.record("capabilities.probe_ms", statistics.median(samples))
    acceleration = report.get("acceleration")
    if acceleration is None:
        bench.note("no acceleration report in this checkout")
        return
    bench.record("capabilities.accelerated_codecs", len(report.get("accelerated", [])), "codecs")
    bench.note("acceleration policy=%s methods=%s codecs=%s" % (
        acceleration["policy"], list(acceleration["methods"]),
        {codec: backend["name"] for codec, backend in acceleration["codecs"].items()}))


def measure_startup(bench, services_factory):
    """Time until the slideshow path is usable, and until the UI is ready."""
    from unittest.mock import patch

    def slow_addresses():
        time.sleep(1.5)
        return ["10.0.0.5"]

    with patch("web_server.lan_addresses", side_effect=slow_addresses):
        started = time.perf_counter()
        services = services_factory()
        ready_ms = (time.perf_counter() - started) * 1000
        try:
            bench.record("startup.slideshow_ready_ms", ready_ms)
            if hasattr(services, "decoder") and services.decoder is not None:
                bench.record("startup.decoder_usable_after_ms", ready_ms)
            state = getattr(services.server, "state", "ready")
            bench.note("server state immediately after construction: %s" % state)
            wait = getattr(services.server, "wait_ready", None)
            if wait is not None:
                started = time.perf_counter()
                wait(timeout=30)
                bench.record("startup.server_ready_after_ms", (time.perf_counter() - started) * 1000)
            else:
                bench.record("startup.server_ready_after_ms", 0.0)
        finally:
            services.close()


def measure_decoder(bench, library, items, sizes=(480, 272), repeats=3):
    import player
    from player import Decoder
    from settings import DEFAULTS

    for label, item, settings in items:
        decoder = Decoder(library)
        try:
            size = sizes
            first, _ = timed(lambda: None)
            while not decoder.events.empty():
                decoder.events.get_nowait()
            started = time.monotonic()
            decoder.request(item, size, settings)
            frames, first_frame = [], None
            deadline = started + 120
            while time.monotonic() < deadline:
                try:
                    generation, kind, value, seconds = decoder.events.get(timeout=0.05)
                except queue.Empty:
                    continue
                if kind == "frame":
                    if first_frame is None:
                        first_frame = time.monotonic() - started
                    frames.append(seconds)
                elif kind in ("done", "error"):
                    break
            total = time.monotonic() - started
            if first_frame is None:
                bench.note("%s produced no frames" % label)
                continue
            bench.record("%s.first_frame_ms" % label, (first_frame or 0) * 1000)
            bench.record("%s.produce_rate_fps" % label, len(frames) / max(total, 1e-9), "fps")
            playthrough = sum(frames) / max(1, settings.get("repeats", 1))
            bench.record("%s.media_seconds_per_repeat" % label, playthrough, "s")
        finally:
            decoder.close()
    bench.record("decoder.lookahead_frames", getattr(player, "LOOKAHEAD", 0), "frames")


def measure_animation_timing(bench, library, item, source_seconds, repeats):
    from player import Decoder, PlaybackClock
    from settings import DEFAULTS

    decoder = Decoder(library)
    try:
        while not decoder.events.empty():
            decoder.events.get_nowait()
        settings = dict(DEFAULTS, repeats=repeats)
        decoder.request(item, (480, 272), settings)
        clock = PlaybackClock()
        durations, first = [], None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                generation, kind, value, seconds = decoder.events.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "frame":
                if first is None:
                    first = time.monotonic()
                clock.arm(seconds, continuous=True)
                durations.append(seconds)
            elif kind in ("done", "error"):
                break
        expected = source_seconds * repeats
        if expected:
            bench.record("animation.media_vs_source_pct", sum(durations) / expected * 100, "%")
        if first is not None and len(durations) > 1:
            bench.record("animation.presentation_seconds", time.monotonic() - first, "s")
    finally:
        decoder.close()


def big_animation_fixture(directory, frames=24, size=(640, 480)):
    """An animation far larger than the per-animation cache allowance."""
    images = animation_frames(frames, size)
    target = directory / "big.webp"
    images[0].save(target, format="WEBP", save_all=True, append_images=images[1:],
                   duration=40, loop=0, quality=80, method=4)
    return target


def measure_replays(bench, library, item, repeats=3):
    """Replaying one animation several times is where repeated decode shows up."""
    from unittest.mock import patch
    from player import Decoder
    from settings import DEFAULTS

    decoder = Decoder(library)
    opens = {"count": 0}
    original = library.open_item

    def counting(item_row):
        opens["count"] += 1
        return original(item_row)

    with patch.object(library, "open_item", side_effect=counting):
        try:
            cpu_before, started = time.process_time(), time.monotonic()
            media_seconds = 0.0
            for _ in range(repeats):
                while not decoder.events.empty():
                    decoder.events.get_nowait()
                decoder.request(item, (480, 272), dict(DEFAULTS, repeats=1), upcoming=[item])
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    try:
                        generation, kind, value, seconds = decoder.events.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if kind == "frame":
                        media_seconds += seconds
                    elif kind in ("done", "error"):
                        break
            wall = time.monotonic() - started
            cpu = time.process_time() - cpu_before
            bench.record("animation.replay_3x_wall_ms", wall * 1000)
            bench.record("animation.replay_3x_media_seconds", media_seconds, "s")
            bench.record("animation.replay_3x_file_opens", opens["count"], "opens")
            if media_seconds:
                bench.record("animation.replay_cpu_per_media_second", cpu / media_seconds, "s")
        finally:
            decoder.close()


def measure_video_processes(bench, library, item, repeats=3, item_source_seconds=None):
    """How many external decoders one item costs, and how long repeats take."""
    from player import Decoder
    from settings import DEFAULTS

    decoder = Decoder(library)
    starts = {"count": 0}
    original = decoder.processes.start

    def counting(*args, **kwargs):
        starts["count"] += 1
        return original(*args, **kwargs)

    decoder.processes.start = counting
    try:
        while not decoder.events.empty():
            decoder.events.get_nowait()
        started = time.monotonic()
        decoder.request(item, (480, 272), dict(DEFAULTS, repeats=repeats))
        frames = 0
        deadline = started + 180
        while time.monotonic() < deadline:
            try:
                generation, kind, value, seconds = decoder.events.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "frame":
                frames += 1
            elif kind in ("done", "error"):
                break
        total = (time.monotonic() - started) * 1000
        bench.record("video.repeats_process_starts", starts["count"], "processes")
        bench.record("video.repeats_total_ms", total)
        bench.record("video.repeats_frames", frames, "frames")
        if frames:
            bench.record("video.ms_per_frame", total / frames)
        if item_source_seconds:
            bench.record("video.delivered_fps",
                         frames / (item_source_seconds * repeats), "fps")
    finally:
        decoder.close()


def measure_video(bench, library, items):
    from player import Decoder
    from settings import DEFAULTS

    for label, item, source_seconds in items:
        decoder = Decoder(library)
        try:
            while not decoder.events.empty():
                decoder.events.get_nowait()
            started = time.monotonic()
            decoder.request(item, (480, 272), dict(DEFAULTS, repeats=1))
            frames, first = [], None
            deadline = started + 120
            while time.monotonic() < deadline:
                try:
                    generation, kind, value, seconds = decoder.events.get(timeout=0.05)
                except queue.Empty:
                    continue
                if kind == "frame":
                    if first is None:
                        first = time.monotonic() - started
                    frames.append(seconds)
                elif kind in ("done", "error"):
                    break
            total = time.monotonic() - started
            if not frames:
                bench.note("%s produced no frames" % label)
                continue
            bench.record("%s.first_frame_ms" % label, (first or 0) * 1000)
            bench.record("%s.produce_rate_fps" % label, len(frames) / max(total, 1e-9), "fps")
            presented = sum(frames)
            bench.record("%s.presented_seconds" % label, presented, "s")
            bench.record("%s.source_seconds" % label, source_seconds, "s")
            if source_seconds:
                bench.record("%s.timing_error_pct" % label,
                             (presented - source_seconds) / source_seconds * 100, "%")
        finally:
            decoder.close()


def measure_conversion(bench, library, processes, fixtures, paths, kind):
    """Time a whole folder of convertible media through the public entry point."""
    from convert import Conversions

    collection = library.create("Benchmark conversions")
    for index in range(3):
        stream, staged = library.temporary_upload()
        with stream:
            stream.write(fixtures["gif"].read_bytes())
        library.add_upload(collection["id"], "clip-%d.gif" % index, staged,
                           {"kind": "gif", "animated": True})
    images = 0
    try:
        conversions = Conversions(library, processes, workers=1)
    except TypeError:
        conversions = Conversions(library, processes)
    try:
        bulk = getattr(conversions, "start_bulk", None)
        started = time.perf_counter()
        if bulk is None:
            bench.note("bulk conversion API unavailable; timing sequential requests")
            for row in library.playlist(collection["id"]):
                conversions.start(collection["id"], row["id"])
                with conversions.condition:
                    conversions.condition.wait_for(
                        lambda: conversions.snapshot()["status"] != "running", timeout=180)
            done, failed = 3, 0
        else:
            bulk("collection", [kind], False, collection["id"])
            with conversions.condition:
                conversions.condition.wait_for(
                    lambda: conversions.snapshot()["job"]["status"]
                    not in ("queued", "running"), timeout=300)
            job = conversions.snapshot()["job"]
            done, failed = job["completed"], job["failed"]
        elapsed = (time.perf_counter() - started) * 1000
        bench.record("convert.items", done + failed, "items")
        bench.record("convert.converted", done, "items")
        bench.record("convert.failed", failed, "items")
        bench.record("convert.total_ms", elapsed)
        if done + failed:
            bench.record("convert.per_item_ms", elapsed / (done + failed))
    finally:
        conversions.close()
    return images


def measure_presentation(bench, paths, collection_id, seconds):
    """Drive the real Tk loop and count frames the UI actually presented."""
    try:
        import tkinter as tk
        from ui import App, Services
    except ImportError as error:
        bench.note("presentation benchmark skipped: %s" % error)
        return
    try:
        root = tk.Tk()
    except tk.TclError as error:
        bench.note("presentation benchmark skipped: %s" % error)
        return
    app = App(root, lambda: Services(paths, "127.0.0.1", 0))
    presented = []
    original = app.present_frame

    def counting(frame):
        presented.append(time.monotonic())
        return original(frame)

    app.present_frame = counting
    try:
        deadline = time.monotonic() + 15
        while app.services is None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.005)
        if app.services is None:
            bench.note("presentation benchmark skipped: services did not start")
            return
        app.play(collection_id)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.001)
        if len(presented) > 1:
            span = presented[-1] - presented[0]
            bench.record("ui.presented_fps", len(presented) / max(span, 1e-9), "fps")
            bench.record("ui.presented_frames", len(presented), "frames")
            bench.record("ui.presented_span_s", span, "s")
        else:
            bench.note("presentation benchmark produced too few frames")
    finally:
        try:
            app.close()
            deadline = time.monotonic() + 10
            while not app.finished and time.monotonic() < deadline:
                root.update()
                time.sleep(0.005)
        finally:
            app.finish()
            try:
                root.destroy()
            except tk.TclError:
                pass


def measure_memory(bench, library, animation_item):
    from player import Decoder
    from settings import DEFAULTS

    decoder = Decoder(library)
    try:
        while not decoder.events.empty():
            decoder.events.get_nowait()
        decoder.request(animation_item, (480, 272), dict(DEFAULTS, repeats=1),
                        upcoming=[animation_item])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if decoder.events.get(timeout=0.1)[1] in ("done", "error"):
                    break
            except queue.Empty:
                continue
        bench.record("memory.animation_cache_bytes", decoder.animation_cache._used(), "bytes")
        bench.record("memory.still_cache_bytes", decoder.still_bytes, "bytes")
    finally:
        decoder.close()


# --------------------------------------------------------------------------- driver

def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    package = Path(args.package).resolve()
    sys.path.insert(0, str(package))

    bench = Bench()
    print("benchmarking %s" % package)
    print(json.dumps(environment(package), indent=2))

    temp = Path(tempfile.mkdtemp(prefix="carousel-bench-")).resolve()
    if args.keep_fixtures:
        print("fixtures kept in %s" % temp)
    fixtures = build_fixtures(temp / "fixtures")

    from storage import Paths
    from library import Library
    from settings import Settings
    from media import Processes, probe

    home = temp / "home"
    home.mkdir()
    os.environ["HOME"] = str(home)
    paths = Paths({"HOME": str(home)})
    library = Library(paths)
    settings = Settings(paths.config)
    collection_id = library.snapshot()[0]["id"]
    processes = Processes()

    def upload(name, raw, info):
        stream, staged = library.temporary_upload()
        with stream:
            stream.write(raw)
        return library.add_upload(collection_id, name, staged, info)

    gif_item = upload("animation.gif", fixtures["gif"].read_bytes(), {"kind": "gif", "animated": True})
    webp_item = upload("animation.webp", fixtures["webp"].read_bytes(),
                       {"kind": "webp", "animated": True})
    upload("still.png", fixtures["still"].read_bytes(), {"kind": "png"})
    for index in range(6):
        upload("photo-%d.jpg" % index, fixtures["photo"].read_bytes(), {"kind": "jpeg"})

    big_path = big_animation_fixture(temp / "fixtures")
    videos = []
    for name in ("vp8", "vp9"):
        if name in fixtures:
            stream, staged = library.temporary_upload()
            with stream:
                stream.write(fixtures[name].read_bytes())
            info = probe(staged, processes)
            item = library.add_upload(collection_id, "clip-%s.webm" % name, staged, info)
            videos.append((name, item, info["duration"]))

    from PIL import Image as pil_image
    with pil_image.open(fixtures["gif"]) as animation:
        gif_seconds = sum(getattr(animation.seek(index) or animation, "info", {}).get("duration", 40)
                          for index in range(animation.n_frames)) / 1000.0
    webp_seconds = gif_seconds

    try:
        measure_capabilities(bench, args.repeats)
        # Binding every interface is what the app does, and it is the slow path
        # that must not delay playback.
        measure_startup(bench, lambda: __import__("ui", fromlist=["Services"]).Services(
            paths, "0.0.0.0", 0))
        measure_decoder(bench, library, [
            ("animation.gif_cold", gif_item, {"image_seconds": 5, "repeats": 1,
                                              "order": "ordered", "loop": False}),
            ("animation.webp_cold", webp_item, {"image_seconds": 5, "repeats": 1,
                                                "order": "ordered", "loop": False}),
        ])
        measure_animation_timing(bench, library, gif_item, gif_seconds, 3)
        bench.record("animation.gif_frames", 24, "frames")
        bench.record("animation.gif_source_seconds", gif_seconds, "s")
        for label, item, duration in videos:
            measure_video(bench, library, [(label, item, duration)])
        del webp_seconds
        if big_path is not None:
            big_item = upload("big.webp", big_path.read_bytes(),
                              {"kind": "webp", "animated": True})
            measure_replays(bench, library, big_item)
        if videos:
            measure_video_processes(bench, library, videos[0][1], repeats=3,
                                    item_source_seconds=videos[0][2])
        measure_memory(bench, library, gif_item)
        measure_conversion(bench, library, processes, fixtures, paths, "gif")
        measure_presentation(bench, paths, collection_id, args.seconds)
    finally:
        processes.close()
        if not args.keep_fixtures:
            shutil.rmtree(temp, ignore_errors=True)

    print("\nresults")
    print(bench.report())
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"environment": environment(package), "results": bench.results,
             "notes": bench.notes}, indent=2))
        print("\nwrote %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
