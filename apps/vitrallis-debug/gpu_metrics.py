"""GPU metrics providers. No privilege escalation or trace configuration at runtime.

The platform installer owns the dedicated, GPU-filtered tracefs instance. Only
its trace_pipe is readable by the desktop account. Never consume the global pipe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import fcntl
import logging
import os
from pathlib import Path
import re
import selectors
import socket
import threading
import time
from typing import Optional


class State(Enum):
    UNSUPPORTED = "No supported GPU utilization provider"
    MISSING_DEVFREQ = "Lima detected; GPU devfreq missing. Run PocketCHIP platform setup and reboot if requested."
    TRACE_UNAVAILABLE = "GPU devfreq available; devfreq_monitor unavailable or not configured"
    WAITING = "No recent devfreq_monitor samples; GPU may be suspended"
    WORKING = "devfreq_monitor"


@dataclass(frozen=True)
class Sample:
    device: str
    frequency_hz: int
    polling_ms: int
    load: int
    timestamp: Optional[float] = None


def parse_sample(line: str) -> Optional[Sample]:
    """Accept only complete kernel devfreq_monitor records with bounded fields."""
    if len(line) > 4096 or "devfreq_monitor:" not in line:
        return None
    fields = line.split("devfreq_monitor:", 1)[1].split()
    values = {}
    for field in fields:
        key, sep, value = field.partition("=")
        if not sep or key in values:
            return None
        values[key] = value
    if set(values) != {"dev_name", "freq", "polling_ms", "load"}:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", values["dev_name"]):
        return None
    if any(not re.fullmatch(r"[0-9]{1,20}", values[key]) for key in ("freq", "polling_ms", "load")):
        return None
    frequency, polling, load = (int(values[key]) for key in ("freq", "polling_ms", "load"))
    if not (0 < frequency < 2**64 and 0 < polling <= 60000 and 0 <= load <= 100):
        return None
    prefix = line.split("devfreq_monitor:", 1)[0]
    timestamp = re.search(r" ([0-9]{1,14}\.[0-9]{1,9}):\s*$", prefix)
    return Sample(values["dev_name"], frequency, polling, load,
                  float(timestamp[1]) if timestamp else None)


class Records:
    """Bound partial records, discard oversized lines through their next newline."""
    def __init__(self, device: str):
        self.device = device
        self.pending = b""
        self.discard = False

    def feed(self, data: bytes) -> Optional[Sample]:
        newest = None
        for part in data.splitlines(keepends=True):
            complete = part.endswith(b"\n")
            if not self.discard:
                self.pending += part
                if len(self.pending) > 4096:
                    self.discard, self.pending = True, b""
                elif complete:
                    sample = parse_sample(self.pending.decode("ascii", "replace"))
                    if sample is not None and sample.device == self.device:
                        newest = sample
            if complete:
                self.discard, self.pending = False, b""
        return newest


class TraceReader:
    """Blocking readiness wait in one thread; socket wakeup gives prompt shutdown."""
    def __init__(self, path: Path, device: str, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.latest = None
        self.error = None
        self.reader = self.writer = None
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.reader, self.writer = socket.socketpair()
            self.records = Records(device)
            self.thread = threading.Thread(target=self._run, name="vitrallis-gpu-trace", daemon=True)
            self.thread.start()
        except BaseException:
            os.close(self.fd)
            if self.reader: self.reader.close()
            if self.writer: self.writer.close()
            raise

    def _run(self):
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.fd, selectors.EVENT_READ)
                selector.register(self.reader, selectors.EVENT_READ)
                while True:
                    ready = selector.select()
                    if any(key.fileobj is self.reader for key, _ in ready):
                        return
                    try:
                        data = os.read(self.fd, 16384)
                    except BlockingIOError:
                        continue
                    if not data:
                        raise OSError("trace instance stopped")
                    sample = self.records.feed(data)
                    if sample is not None and sample.timestamp is not None:
                        with self.lock:
                            self.latest = (sample.timestamp, sample)
        except OSError as error:
            with self.lock:
                self.error = str(error)
        finally:
            os.close(self.fd)

    def sample(self):
        with self.lock:
            if self.error or self.latest is None:
                return None
            when, sample = self.latest
            return sample if 0 <= self.clock() - when <= max(2.0, sample.polling_ms / 500) else None

    def close(self):
        # Owner serializes collect/close, including failed-provider replacement.
        self.writer.send(b"x")
        self.thread.join()
        self.writer.close()
        self.reader.close()


@dataclass(frozen=True)
class Device:
    name: str
    driver: str
    path: Path
    devfreq: Optional[Path]


def lima_device(sys_root: Path) -> Optional[Device]:
    """Match DRM to its bound kernel device, then match devfreq's parent device.

    The Lima driver directory also covers GPUs without a DRM primary card node.
    A loaded module by itself is never evidence of a bound device.
    """
    try:
        candidates = [card / "device" for card in sorted((sys_root / "class/drm").glob("card*"))
                      if card.name[4:].isdigit()]
        driver = sys_root / "bus/platform/drivers/lima"
        candidates += sorted(driver.glob("*"))
        for candidate in candidates:
            try:
                path = candidate.resolve(strict=True)
                if (path / "driver").resolve(strict=True).name != "lima":
                    continue
            except OSError:
                continue
            devfreq = None
            for entry in sorted((sys_root / "class/devfreq").glob("*")):
                try:
                    resolved = entry.resolve(strict=True)
                except OSError:
                    continue
                if resolved.parent.name == "devfreq" and resolved.parent.parent == path:
                    devfreq = entry
                    break
                try:
                    if (entry / "device").resolve(strict=True) == path:
                        devfreq = entry
                        break
                except OSError:
                    continue
            return Device(path.name, "Lima", path, devfreq)
    except OSError:
        pass
    return None


class LimaProvider:
    """Nonfatal provider with cached discovery and separately exposed frequency."""
    def __init__(self, sys_root: Path, clock=time.monotonic, reader_factory=TraceReader):
        self.sys_root, self.clock, self.reader_factory = sys_root, clock, reader_factory
        self.device = None
        self.reader = None
        self.state = State.UNSUPPORTED
        self.frequency_hz = None
        self.next_discovery = 0.0
        self.lock = threading.Lock()
        self.closed = False

    def collect(self):
        with self.lock:
            if self.closed:
                return None
            now = self.clock()
            if now >= self.next_discovery:
                device = lima_device(self.sys_root)
                if device != self.device or (self.reader and self.reader.error):
                    if self.reader: self.reader.close()
                    self.reader = None
                self.device = device
                self.next_discovery = now + 30
                if device and device.devfreq and self.reader is None:
                    try:
                        self.reader = self.reader_factory(
                            Path("/run/vitrallis-gpu/trace_pipe"), device.name)
                        logging.info("GPU utilization provider=Lima source=devfreq_monitor device=%s", device.name)
                    except OSError:
                        pass
            self.frequency_hz = None
            if self.device is None:
                self.state = State.UNSUPPORTED
                return None
            if self.device.devfreq is None:
                self.state = State.MISSING_DEVFREQ
                return None
            try:
                value = (self.device.devfreq / "cur_freq").read_text()[:64].strip()
                if value.isdecimal() and 0 < int(value) < 2**64:
                    self.frequency_hz = int(value)
            except (OSError, ValueError):
                pass
            self.state = State.TRACE_UNAVAILABLE
            if self.reader is None or self.reader.error:
                return None
            sample = self.reader.sample()
            self.state = State.WORKING if sample else State.WAITING
            # cur_freq describes the current clock, which may differ from the last
            # utilization interval. Never infer either metric from the other.
            return sample

    def close(self):
        with self.lock:
            self.closed = True
            if self.reader:
                self.reader.close()
                self.reader = None
