"""Bounded devfreq_monitor sampling in an isolated tracefs instance.

No global trace settings, privilege escalation or frequency/governor changes.
Instance creation needs delegated tracefs access; denied access stays unavailable.
"""
from collections import deque
import os
from pathlib import Path
import re
import time
import threading
import uuid


EVENT = re.compile(
    r"\s(?P<time>[0-9]+\.[0-9]+):\s+devfreq_monitor:\s+"
    r"dev_name=(?P<device>[^\s]+)\s+freq=[0-9]+\s+"
    r"polling_ms=(?P<interval>[0-9]+)\s+load=(?P<load>[0-9]+)\s*$"
)
WINDOW_SECONDS = 2.0
MAX_BYTES = 262144


def parse_event(line):
    if len(line) > 4096:
        return None
    match = EVENT.search(line)
    if not match:
        return None
    stamp = float(match['time'])
    interval, load = int(match['interval']), int(match['load'])
    if not 0 < interval <= 60000 or not 0 <= load <= 100:
        return None
    return match['device'], stamp, interval, load


class DevfreqMonitor:
    def __init__(self, sys_root=Path('/sys'), clock=time.monotonic):
        self.sys_root, self.clock = sys_root, clock
        self.instance = None
        self.fd = None
        self.pending = b''
        self.samples = {}
        self.retry_at = 0.0
        self.closed = False
        self.lock = threading.Lock()
        self.reason = 'devfreq_monitor trace access unavailable'

    @staticmethod
    def _write(path, value):
        # Existing kernel attributes only; never create a regular file fallback.
        fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if os.write(fd, value.encode('ascii')) != len(value):
                raise OSError('Incomplete tracefs attribute write')
        finally:
            os.close(fd)

    def _start(self):
        now = self.clock()
        if self.closed or now < self.retry_at:
            return
        self.retry_at = now + 30
        for root in (self.sys_root / 'kernel/tracing', self.sys_root / 'kernel/debug/tracing'):
            event = root / 'events/devfreq/devfreq_monitor/enable'
            try:
                if not event.is_file():
                    continue
                # Only our freshly-created instance may be configured or removed.
                instance = root / 'instances' / ('vitrallis-debug-' + uuid.uuid4().hex)
                instance.mkdir(mode=0o700)
                self.instance = instance
                self._write(instance / 'tracing_on', '0')
                self._write(instance / 'buffer_size_kb', '64')
                self._write(instance / 'trace_clock', 'mono')
                self.fd = os.open(instance / 'trace_pipe', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                self._write(instance / 'events/devfreq/devfreq_monitor/enable', '1')
                self._write(instance / 'tracing_on', '1')
                self.reason = 'Waiting for devfreq_monitor GPU samples'
                return
            except OSError:
                self._release()
                self.reason = 'devfreq_monitor needs delegated tracefs instance access'

    def ingest(self, data, devices, now):
        """Accept only fresh events for discovered GPU devices; preserve partial lines."""
        lines = (self.pending + data).split(b'\n')
        self.pending = lines.pop()[-4096:]
        for raw in lines:
            parsed = parse_event(raw.decode('ascii', 'replace'))
            if parsed is None:
                continue
            device, stamp, interval, load = parsed
            if device not in devices or not now - WINDOW_SECONDS <= stamp <= now:
                continue
            values = self.samples.setdefault(device, deque(maxlen=256))
            if values and stamp <= values[-1][0]:
                continue
            values.append((stamp, interval, load))
        for device in list(self.samples):
            values = self.samples[device]
            while values and values[0][0] < now - WINDOW_SECONDS:
                values.popleft()
            if device not in devices or not values:
                del self.samples[device]

    def collect(self, devices):
        with self.lock:
            return self._collect(devices)

    def _collect(self, devices):
        if self.closed:
            return None
        if not devices:
            self._release()
            return None
        if self.fd is None:
            self._start()
        if self.fd is None:
            return None
        data = bytearray()
        try:
            while len(data) < MAX_BYTES:
                try:
                    chunk = os.read(self.fd, min(65536, MAX_BYTES - len(data)))
                except BlockingIOError:
                    break
                if not chunk:
                    break
                data.extend(chunk)
        except OSError:
            self._release()
            self.reason = 'devfreq_monitor stream unavailable'
            return None
        self.ingest(data, devices, self.clock())
        for device in sorted(self.samples):
            values = self.samples[device]
            total = sum(interval for _, interval, _ in values)
            if total:
                percent = sum(interval * load for _, interval, load in values) / total
                return device, percent, str(self.instance / 'events/devfreq/devfreq_monitor') + ' · 2 s average'
        self.reason = 'No fresh devfreq_monitor GPU load samples'
        return None

    def _release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.instance is not None:
            for leaf in ('tracing_on', 'events/devfreq/devfreq_monitor/enable'):
                try:
                    self._write(self.instance / leaf, '0')
                except OSError:
                    pass
            try:
                self.instance.rmdir()  # tracefs removes its virtual children itself.
            except OSError:
                pass
            self.instance = None
        self.pending = b''
        self.samples.clear()

    def close(self):
        with self.lock:
            self.closed = True
            self._release()
