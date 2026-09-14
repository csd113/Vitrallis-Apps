"""Linux hardware identity and offline diagnostic collection for Vitrallis Debug.

Imports are deliberately side-effect free.  All filesystem and command access is
performed only when a collector method is called, making the parsing code usable
with fixture data on a development machine.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import csv
import json
import math
from pathlib import Path
import platform
import socket
import shutil
import subprocess
import time
from typing import Callable, Iterable, List, Optional

from hardware import HardwareCollector, HardwareInfo
from devfreq import DevfreqMonitor


MAX_HISTORY = 60
CommandRunner = Callable[[List[str]], Optional[str]]
ReadText = Callable[[Path], Optional[str]]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None


def _number(text: object) -> Optional[float]:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _local_command(arguments: list[str]) -> Optional[str]:
    """Run an optional local utility without a shell or unbounded retained output."""
    try:
        result = subprocess.run(
            arguments, check=False, shell=False, timeout=1.5,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout[:262_144].decode("utf-8", "replace")


@dataclass(frozen=True)
class CpuTimes:
    busy: int
    total: int


def parse_proc_stat(text: Optional[str]) -> tuple[Optional[CpuTimes], dict[str, CpuTimes]]:
    """Parse aggregate and per-core counters without double-counting guest time."""
    aggregate: Optional[CpuTimes] = None
    cores: dict[str, CpuTimes] = {}
    for line in (text or "").splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith("cpu") or not fields[0][3:].isdigit() and fields[0] != "cpu":
            continue
        try:
            values = [int(value) for value in fields[1:]]
        except ValueError:
            continue
        if len(values) < 4 or any(value < 0 for value in values):
            continue
        values += [0] * (8 - len(values))
        user, nice, system, idle, iowait, irq, softirq, steal = values[:8]
        item = CpuTimes(user + nice + system + irq + softirq + steal,
                        user + nice + system + idle + iowait + irq + softirq + steal)
        if item.total <= 0:
            continue
        if fields[0] == "cpu":
            aggregate = item
        else:
            cores[fields[0]] = item
    return aggregate, cores


def utilization(previous: Optional[CpuTimes], current: Optional[CpuTimes]) -> Optional[float]:
    if previous is None or current is None:
        return None
    total_delta = current.total - previous.total
    busy_delta = current.busy - previous.busy
    if total_delta <= 0 or busy_delta < 0 or busy_delta > total_delta:
        return None
    return round(100.0 * busy_delta / total_delta, 1)


class CpuTracker:
    def __init__(self) -> None:
        self.previous: Optional[CpuTimes] = None
        self.previous_cores: dict[str, CpuTimes] = {}

    def update(self, stat_text: Optional[str]) -> tuple[Optional[float], dict[str, Optional[float]]]:
        current, current_cores = parse_proc_stat(stat_text)
        overall = utilization(self.previous, current)
        per_core = {name: utilization(self.previous_cores.get(name), value)
                    for name, value in current_cores.items()}
        if current is not None:
            self.previous = current
        self.previous_cores = current_cores
        return overall, per_core


@dataclass(frozen=True)
class Frequency:
    mhz: float
    source: str
    path: str


def _frequency_from_khz(value: Optional[float], source: str, path: Path) -> Optional[Frequency]:
    if value is None or value <= 0 or value > 20_000_000:
        return None
    return Frequency(round(value / 1000.0, 1), source, str(path))


def discover_frequency(sys_root: Path = Path("/sys"), proc_cpuinfo: Optional[str] = None,
                       read_text: ReadText = _read_text) -> tuple[Optional[Frequency], list[Frequency]]:
    """Discover cpufreq policy paths first, then CPU paths, then /proc CPU MHz."""
    bases: list[Path] = []
    policy_root = sys_root / "devices/system/cpu/cpufreq"
    try:
        bases.extend(sorted(path for path in policy_root.glob("policy*") if path.is_dir()))
    except OSError:
        pass
    try:
        bases.extend(sorted(path / "cpufreq" for path in (sys_root / "devices/system/cpu").glob("cpu[0-9]*")
                            if (path / "cpufreq").is_dir()))
    except OSError:
        pass
    readings: list[Frequency] = []
    seen: set[str] = set()
    for base in bases:
        for name, label in (("cpuinfo_cur_freq", "measured"),
                            ("scaling_cur_freq", "driver-reported/requested")):
            path = base / name
            raw = read_text(path)
            reading = _frequency_from_khz(_number(raw), label, path)
            if reading and str(path) not in seen:
                readings.append(reading)
                seen.add(str(path))
                break
    if readings:
        return readings[0], readings
    for line in (proc_cpuinfo or "").splitlines():
        if ":" in line and line.split(":", 1)[0].strip().lower() == "cpu mhz":
            value = _number(line.split(":", 1)[1])
            if value and 0 < value < 20_000:
                reading = Frequency(round(value, 1), "kernel-reported", "/proc/cpuinfo")
                return reading, [reading]
    return None, []


def read_frequency_limits(sys_root: Path = Path("/sys"), read_text: ReadText = _read_text) -> list[tuple[str, Optional[float], Optional[float]]]:
    result: list[tuple[str, Optional[float], Optional[float]]] = []
    root = sys_root / "devices/system/cpu/cpufreq"
    try:
        bases = sorted(path for path in root.glob("policy*") if path.is_dir())
    except OSError:
        bases = []
    for base in bases:
        low = _frequency_from_khz(_number(read_text(base / "cpuinfo_min_freq")), "limit", base)
        high = _frequency_from_khz(_number(read_text(base / "cpuinfo_max_freq")), "limit", base)
        result.append((base.name, low.mhz if low else None, high.mhz if high else None))
    return result


@dataclass(frozen=True)
class Memory:
    total_kib: int
    available_kib: int
    free_kib: Optional[int]
    buffers_kib: Optional[int]
    cache_kib: Optional[int]
    swap_total_kib: Optional[int]
    swap_free_kib: Optional[int]
    estimated: bool = False

    @property
    def used_kib(self) -> int:
        return max(0, self.total_kib - self.available_kib)

    @property
    def percent(self) -> float:
        return 100.0 * self.used_kib / self.total_kib


def parse_meminfo(text: Optional[str]) -> Optional[Memory]:
    fields: dict[str, int] = {}
    for line in (text or "").splitlines():
        key, colon, remainder = line.partition(":")
        parts = remainder.split()
        if not colon or len(parts) < 2 or parts[1] != "kB":
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        if value >= 0:
            fields[key] = value
    total = fields.get("MemTotal")
    if not total or total <= 0:
        return None
    available = fields.get("MemAvailable")
    estimated = available is None
    if available is None:
        essentials = ("MemFree", "Buffers", "Cached")
        if not all(key in fields for key in essentials):
            return None
        available = fields["MemFree"] + fields["Buffers"] + fields["Cached"]
        available += fields.get("SReclaimable", 0) - fields.get("Shmem", 0)
    available = min(total, max(0, available))
    return Memory(total, available, fields.get("MemFree"), fields.get("Buffers"),
                  fields.get("Cached"), fields.get("SwapTotal"), fields.get("SwapFree"), estimated)


@dataclass(frozen=True)
class TemperatureSensor:
    label: str
    kind: str
    celsius: float
    path: str
    critical_celsius: Optional[float] = None
    selected: bool = False


def _temperature(raw: Optional[str]) -> Optional[float]:
    value = _number(raw)
    if value is None:
        return None
    if abs(value) >= 500:
        value /= 1000.0
    return round(value, 1) if -40.0 <= value <= 200.0 else None


def discover_sensors(sys_root: Path = Path("/sys"), read_text: ReadText = _read_text) -> list[TemperatureSensor]:
    sensors: list[TemperatureSensor] = []
    thermal_root = sys_root / "class/thermal"
    try:
        zones = sorted(path for path in thermal_root.glob("thermal_zone*") if path.is_dir())
    except OSError:
        zones = []
    for zone in zones:
        kind = (read_text(zone / "type") or "unknown thermal zone").strip() or "unknown thermal zone"
        value = _temperature(read_text(zone / "temp"))
        if value is not None:
            critical = _temperature(read_text(zone / "trip_point_0_temp"))
            sensors.append(TemperatureSensor(kind, kind, value, str(zone / "temp"), critical))
    hwmon_root = sys_root / "class/hwmon"
    try:
        monitors = sorted(path for path in hwmon_root.glob("hwmon*") if path.is_dir())
    except OSError:
        monitors = []
    for monitor in monitors:
        kind = (read_text(monitor / "name") or "hwmon").strip() or "hwmon"
        try:
            inputs = sorted(monitor.glob("temp*_input"))
        except OSError:
            inputs = []
        for input_path in inputs:
            value = _temperature(read_text(input_path))
            if value is None:
                continue
            stem = input_path.name[:-len("_input")]
            label = (read_text(monitor / f"{stem}_label") or stem).strip() or stem
            critical = _temperature(read_text(monitor / f"{stem}_crit"))
            sensors.append(TemperatureSensor(label, kind, value, str(input_path), critical))
    if not sensors:
        return []
    preferred = next((item for item in sensors if any(word in (item.label + " " + item.kind).lower()
                                                 for word in ("cpu", "soc", "package", "core"))), sensors[0])
    return [TemperatureSensor(item.label, item.kind, item.celsius, item.path,
                              item.critical_celsius, item.path == preferred.path) for item in sensors]


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    state: str
    addresses_v4: tuple[str, ...] = ()
    addresses_v6: tuple[str, ...] = ()
    rx_bytes: Optional[int] = None
    tx_bytes: Optional[int] = None

    @property
    def usable(self) -> bool:
        return self.name != "lo" and self.state.upper() in {"UP", "UNKNOWN"} and bool(self.addresses_v4 + self.addresses_v6)


@dataclass(frozen=True)
class Network:
    hostname: str
    interfaces: tuple[NetworkInterface, ...]
    default_interface: Optional[str]
    gateway: Optional[str]

    @property
    def primary(self) -> Optional[NetworkInterface]:
        if self.default_interface:
            chosen = next((item for item in self.interfaces if item.name == self.default_interface and item.usable), None)
            if chosen:
                return chosen
        return next((item for item in self.interfaces if item.usable), None)


def _ip_json(raw: Optional[str]) -> list[dict[str, object]]:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) and all(isinstance(item, dict) for item in value) else []


def parse_network(addresses: Optional[str], routes: Optional[str], hostname: Optional[str] = None) -> Network:
    interfaces: list[NetworkInterface] = []
    for item in _ip_json(addresses):
        name = item.get("ifname")
        if not isinstance(name, str) or not name:
            continue
        v4: list[str] = []
        v6: list[str] = []
        for info in item.get("addr_info", []) if isinstance(item.get("addr_info"), list) else []:
            if not isinstance(info, dict):
                continue
            local, family = info.get("local"), info.get("family")
            prefix = info.get("prefixlen")
            if not isinstance(local, str) or not isinstance(prefix, int):
                continue
            rendered = f"{local}/{prefix}"
            if family == "inet":
                v4.append(rendered)
            elif family == "inet6":
                v6.append(rendered)
        stats = item.get("stats64") if isinstance(item.get("stats64"), dict) else {}
        rx = stats.get("rx", {}).get("bytes") if isinstance(stats.get("rx"), dict) else None
        tx = stats.get("tx", {}).get("bytes") if isinstance(stats.get("tx"), dict) else None
        interfaces.append(NetworkInterface(name, str(item.get("operstate", "UNKNOWN")), tuple(v4), tuple(v6),
                                           rx if isinstance(rx, int) and rx >= 0 else None,
                                           tx if isinstance(tx, int) and tx >= 0 else None))
    default_interface = gateway = None
    for route in _ip_json(routes):
        device = route.get("dev")
        if isinstance(device, str) and device:
            default_interface = device
            via = route.get("gateway")
            gateway = via if isinstance(via, str) else None
            break
    return Network(hostname or socket.gethostname() or "unavailable", tuple(interfaces), default_interface, gateway)


@dataclass(frozen=True)
class GpuReading:
    name: str
    percent: float
    source: str


class GpuCollector:
    """Read documented GPU counters; never infer load from frequency or FPS.

    Discovery is cached for 30 seconds. GPU devfreq devices use a private
    devfreq_monitor trace instance when tracefs permissions allow it.
    """
    def __init__(self, sys_root: Path, read_text: ReadText = _read_text,
                 runner: CommandRunner = _local_command,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.sys_root, self.read_text, self.runner, self.clock = sys_root, read_text, runner, clock
        self.sources: list[tuple[str, Path]] = []
        self.next_discovery = 0.0
        self.nvidia: Optional[str] = None
        self.devfreq_devices: set[str] = set()
        self.monitor = DevfreqMonitor(sys_root, clock)

    def collect(self) -> Optional[GpuReading]:
        now = self.clock()
        if now >= self.next_discovery:
            self.sources = []
            try:
                cards = sorted((self.sys_root / "class/drm").glob("card[0-9]*"))
                for card in cards:
                    if not card.name[4:].isdigit():
                        continue
                    path = card / "device/gpu_busy_percent"
                    if path.is_file():
                        self.sources.append((card.name, path))
            except OSError:
                pass
            try:
                self.devfreq_devices = {node.name for node in (self.sys_root / "class/devfreq").glob("*gpu*") if node.is_dir()}
            except OSError:
                self.devfreq_devices = set()
            self.nvidia = shutil.which("nvidia-smi")
            self.next_discovery = now + 30.0
        for name, path in self.sources:
            percent = _number(self.read_text(path))
            if percent is not None and 0 <= percent <= 100:
                self.monitor.collect(set())
                return GpuReading(name, percent, str(path))
        reading = self.monitor.collect(self.devfreq_devices)
        if reading is not None:
            return GpuReading(*reading)
        if self.nvidia:
            output = self.runner([self.nvidia, "--query-gpu=name,utilization.gpu",
                                  "--format=csv,noheader,nounits", "--id=0"])
            try:
                row = next(csv.reader((output or "").splitlines()), [])
            except csv.Error:
                row = []
            if len(row) == 2:
                percent = _number(row[1])
                if percent is not None and 0 <= percent <= 100:
                    return GpuReading(row[0].strip()[:160], percent, "nvidia-smi / GPU 0")
        return None

    def close(self) -> None:
        self.monitor.close()


@dataclass
class Snapshot:
    sampled_at: float
    cpu_percent: Optional[float]
    per_core: dict[str, Optional[float]]
    cpu_model: str
    cpu_count: int
    frequency: Optional[Frequency]
    frequency_limits: list[tuple[str, Optional[float], Optional[float]]]
    memory: Optional[Memory]
    sensors: list[TemperatureSensor]
    network: Optional[Network]
    errors: dict[str, str] = field(default_factory=dict)
    architecture: str = ""
    governors: list[str] = field(default_factory=list)
    load_averages: Optional[tuple[float, float, float]] = None
    uptime_seconds: Optional[float] = None
    gpu: Optional[GpuReading] = None
    hardware: HardwareInfo = field(default_factory=HardwareInfo)


class SystemCollector:
    """Single-cycle collector. It does not create threads or GUI resources."""
    def __init__(self, proc_root: Path = Path("/proc"), sys_root: Path = Path("/sys"),
                 runner: CommandRunner = _local_command, read_text: ReadText = _read_text,
                 clock: Callable[[], float] = time.monotonic,
                 hardware_collector: Optional[HardwareCollector] = None) -> None:
        self.proc_root, self.sys_root = proc_root, sys_root
        self.runner, self.read_text, self.clock = runner, read_text, clock
        self.gpu = GpuCollector(sys_root, read_text, runner, clock)
        self.cpu = CpuTracker()
        self.hardware = hardware_collector or HardwareCollector(proc_root=proc_root, sys_root=sys_root)

    def collect(self, include_network: bool = True) -> Snapshot:
        errors: dict[str, str] = {}
        stat = self.read_text(self.proc_root / "stat")
        percent, per_core = self.cpu.update(stat)
        if stat is None:
            errors["cpu"] = "Cannot read /proc/stat"
        cpuinfo = self.read_text(self.proc_root / "cpuinfo")
        hardware = self.hardware.collect()
        model = hardware.cpu_name
        frequency, _ = discover_frequency(self.sys_root, cpuinfo, self.read_text)
        memory = parse_meminfo(self.read_text(self.proc_root / "meminfo"))
        if memory is None:
            errors["memory"] = "Memory data unavailable"
        gpu = self.gpu.collect()
        if gpu is None:
            errors["gpu"] = (self.gpu.monitor.reason if self.gpu.devfreq_devices else
                             "This driver exposes no supported GPU utilization counter")
        sensors = discover_sensors(self.sys_root, self.read_text)
        network = None
        if include_network:
            raw_addresses = self.runner(["ip", "-j", "address", "show"])
            raw_routes = self.runner(["ip", "-j", "route", "show", "default"])
            if raw_addresses is None:
                errors["network"] = "Local ip utility unavailable or denied"
            else:
                network = parse_network(raw_addresses, raw_routes)
        return Snapshot(self.clock(), percent, per_core, model, max(1, (os_cpu_count() or 1)), frequency,
                        read_frequency_limits(self.sys_root, self.read_text), memory, sensors, network, errors,
                        platform.machine() or "unknown", read_governors(self.sys_root, self.read_text),
                        parse_load_averages(self.read_text(self.proc_root / "loadavg")),
                        parse_uptime(self.read_text(self.proc_root / "uptime")), gpu, hardware)

    def close(self) -> None:
        self.gpu.close()


def os_cpu_count() -> Optional[int]:
    try:
        import os
        return os.cpu_count()
    except (ImportError, OSError):
        return None


def read_governors(sys_root: Path = Path("/sys"), read_text: ReadText = _read_text) -> list[str]:
    root = sys_root / "devices/system/cpu/cpufreq"
    try:
        policies = sorted(path for path in root.glob("policy*") if path.is_dir())
    except OSError:
        policies = []
    values = []
    for policy in policies:
        governor = (read_text(policy / "scaling_governor") or "").strip()
        if governor:
            values.append(f"{policy.name}: {governor}")
    return values


def parse_load_averages(text: Optional[str]) -> Optional[tuple[float, float, float]]:
    parts = (text or "").split()
    if len(parts) < 3:
        return None
    values = tuple(_number(value) for value in parts[:3])
    return values if all(value is not None and value >= 0 for value in values) else None


def parse_uptime(text: Optional[str]) -> Optional[float]:
    parts = (text or "").split()
    value = _number(parts[0] if parts else None)
    return value if value is not None and value >= 0 else None


class History:
    def __init__(self, limit: int = MAX_HISTORY) -> None:
        self.values: deque[Optional[float]] = deque(maxlen=limit)

    def add(self, value: Optional[float]) -> None:
        self.values.append(value if value is not None and math.isfinite(value) else None)

    def items(self) -> tuple[Optional[float], ...]:
        return tuple(self.values)
