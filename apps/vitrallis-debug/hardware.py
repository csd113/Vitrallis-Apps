"""Read-only Linux CPU/GPU and driver identification, cached for this launch.

No probing happens on import or construction. The diagnostic worker invokes
collect(), keeping platform utilities and filesystem access off the Tk thread.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import subprocess
import threading
from typing import Callable, List, Optional


MAX_OUTPUT = 1_048_576
MAX_DEVICES = 64
Runner = Callable[[List[str]], Optional[str]]
Reader = Callable[[Path], Optional[str]]


def read_text(path: Path) -> Optional[str]:
    try:
        with path.open('r', encoding='utf-8', errors='replace') as stream:
            return stream.read(MAX_OUTPUT)
    except (OSError, UnicodeError):
        return None


def run_probe(arguments: list[str]) -> Optional[str]:
    """Bound execution and retained output without a shell or persistent files."""
    try:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
    except OSError:
        return None
    output = bytearray()
    overflow = threading.Event()

    def drain() -> None:
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                if len(output) + len(chunk) > MAX_OUTPUT:
                    overflow.set()
                    process.kill()
                    break
                output.extend(chunk)
        except OSError:
            overflow.set()
        finally:
            process.stdout.close()

    reader = threading.Thread(target=drain, name='vitrallis-hardware-output', daemon=True)
    try:
        reader.start()
    except RuntimeError:
        process.kill()
        process.wait()
        process.stdout.close()
        return None
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        reader.join(timeout=1)
        return None
    reader.join(timeout=1)
    if reader.is_alive() or overflow.is_set() or process.returncode:
        return None
    return output.decode('utf-8-sig', 'replace')


def _name(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = ' '.join(value.replace('\x00', ' ').split())[:512]
    if not value or value.isdecimal() or value.lower() in {'unknown', 'none', 'n/a', 'to be filled by o.e.m.'}:
        return None
    return value


def _compatible_name(value: str) -> Optional[str]:
    name = _name(value)
    if name and name.startswith('arm,'):
        return 'ARM ' + name.split(',', 1)[1].title()
    return name


@dataclass(frozen=True)
class DriverInfo:
    name: str
    source: str
    module: Optional[str] = None
    version: Optional[str] = None
    srcversion: Optional[str] = None


@dataclass(frozen=True)
class DeviceIdentity:
    name: str
    source: str
    identifier: str = ''
    aliases: tuple[str, ...] = ()
    driver: Optional[DriverInfo] = None
    compatibles: tuple[str, ...] = ()


@dataclass(frozen=True)
class HardwareInfo:
    cpus: tuple[DeviceIdentity, ...] = ()
    gpus: tuple[DeviceIdentity, ...] = ()
    displays: tuple[DeviceIdentity, ...] = ()
    board: Optional[DeviceIdentity] = None
    soc: Optional[DeviceIdentity] = None
    kernel_release: str = ''
    cpu_drivers: tuple[DriverInfo, ...] = ()
    graphics_modules: tuple[DriverInfo, ...] = ()

    @property
    def cpu_name(self) -> str:
        return ' / '.join(dict.fromkeys(item.name for item in self.cpus)) or 'CPU name unavailable'

    def gpu_name(self, counter_name: Optional[str] = None) -> str:
        if counter_name:
            for device in self.gpus:
                if counter_name in (device.identifier, device.name, *device.aliases):
                    return device.name
            # A counter may identify a newly attached or separately enumerated GPU.
            return counter_name
        if not self.gpus:
            return 'GPU name unavailable'
        return self.gpus[0].name + (f' +{len(self.gpus)-1} more' if len(self.gpus) > 1 else '')


def linux_cpu_names(text: Optional[str]) -> tuple[DeviceIdentity, ...]:
    """Prefer model names over CPU indices, board names and architecture strings."""
    fields = []
    for line in (text or '').splitlines():
        key, colon, value = line.partition(':')
        name = _name(value)
        if colon and name:
            fields.append((key.strip().lower(), name))
    for key in ('model name', 'cpu model', 'processor', 'cpu'):
        names = tuple(dict.fromkeys(value for label, value in fields if label == key))[:MAX_DEVICES]
        if names:
            return tuple(DeviceIdentity(name, f'/proc/cpuinfo · {key}') for name in names)
    return ()


def parse_lspci(text: Optional[str]) -> dict[str, DeviceIdentity]:
    devices = {}
    for block in (text or '')[:MAX_OUTPUT].split('\n\n'):
        fields = dict(line.split(':\t', 1) for line in block.splitlines() if ':\t' in line)
        slot, kind = fields.get('Slot', '').strip(), fields.get('Class', '')
        # PCI base class 03 includes VGA, 3D and other display controllers.
        if not re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]', slot):
            continue
        if not re.search(r'\[03[0-9a-fA-F]{2}\]$', kind):
            continue
        vendor = re.sub(r'\s*\[[0-9a-fA-F]{4}\]$', '', fields.get('Vendor', ''))
        model = re.sub(r'\s*\[[0-9a-fA-F]{4}\]$', '', fields.get('Device', ''))
        name = _name(f'{vendor} {model}')
        if name:
            devices[slot.lower()] = DeviceIdentity(name, 'PCI identification · lspci', slot.lower())
        if len(devices) >= MAX_DEVICES:
            break
    return devices


# These are module-presence hints only, never evidence of a device binding.
GRAPHICS_MODULES = ('vc4', 'v3d', 'lima', 'mali', 'mali_drm', 'ump', 'sun4i_drm',
                    'sunxi', 'panfrost', 'panthor', 'simpledrm', 'bcm2708_fb')
GRAPHICS_DRIVERS = set(GRAPHICS_MODULES) | {'sun4i-drm', 'simple-framebuffer', 'mali-utgard'}
GRAPHICS_NODE = re.compile(r'gpu|mali|v3d|vc4|display-engine', re.IGNORECASE)
GPU_COMPATIBLE = re.compile(r'mali|adreno|powervr|vivante|v3d|vc[456]$', re.IGNORECASE)


def compatible_values(text: Optional[str]) -> tuple[str, ...]:
    return tuple(name for part in (text or '').split('\x00')[:64] if (name := _name(part)))


def graphics_name(values: tuple[str, ...]) -> Optional[str]:
    # A vendor-specific binding can precede the actual GPU IP name.
    for value in values:
        if value.startswith('arm,mali-'):
            return _compatible_name(value)
    for value in values:
        if value.startswith('brcm,') and value.endswith('-v3d'):
            return f'Broadcom V3D ({value.split(",", 1)[1]})'
        if value.startswith('brcm,') and re.search(r'-vc[456]$', value):
            return f'Broadcom VC4 display/graphics ({value.split(",", 1)[1]})'
        if GPU_COMPATIBLE.search(value):
            return _compatible_name(value)
    return None


class HardwareCollector:
    def __init__(self, proc_root: Path = Path('/proc'), sys_root: Path = Path('/sys'),
                 runner: Runner = run_probe, reader: Reader = read_text) -> None:
        self.proc_root, self.sys_root = proc_root, sys_root
        self.runner, self.read = runner, reader
        self.cached: Optional[HardwareInfo] = None

    def collect(self) -> HardwareInfo:
        if self.cached is None:
            self.cached = self._linux()
        return self.cached

    def _paths(self, directory: Path, pattern: str) -> list[Path]:
        try:
            return sorted(directory.glob(pattern))[:512]
        except OSError:
            return []

    def _linux(self) -> HardwareInfo:
        cpus = linux_cpu_names(self.read(self.proc_root / 'cpuinfo'))
        if not cpus or all(item.source.endswith("· processor") or
                           re.match(r'ARMv[0-9]+ Processor\b', item.name, re.IGNORECASE)
                           for item in cpus):
            nodes = self._paths(self.sys_root / 'firmware/devicetree/base/cpus', 'cpu@*')
            if not nodes:
                nodes = self._paths(self.proc_root / 'device-tree/cpus', 'cpu@*')
            found = {}
            for node in nodes:
                compatible = self.read(node / 'compatible') or ''
                name = _compatible_name(compatible.split('\x00')[0])
                if name:
                    found[name] = DeviceIdentity(name, str(node / 'compatible'))
            cpus = tuple(found.values()) or cpus
        pci = parse_lspci(self.runner(['lspci', '-D', '-vmm', '-nn']))
        devices: dict[str, DeviceIdentity] = {}
        for node in self._paths(self.sys_root / 'class/drm', '*'):
            if re.fullmatch(r'(?:card|renderD)[0-9]+', node.name):
                self._add_graphics(devices, node / 'device', pci, node.name)
        # Devfreq can expose Lima/Mali even without a render-node alias.
        for node in self._paths(self.sys_root / 'class/devfreq', '*gpu*'):
            device = node / 'device'
            if not device.exists():
                canonical = self._resolve(node)
                # Linux devfreq class links point into DEVICE/devfreq/NAME.
                if canonical is None or canonical.parent.name != 'devfreq':
                    continue
                device = canonical.parent.parent
            self._add_graphics(devices, device, pci, node.name)
        # Always enumerate platform GPUs: a display-only DRM card may exist while
        # Mali uses a separate platform driver with no DRM interface.
        for node in self._paths(self.sys_root / 'bus/platform/devices', '*'):
            driver = self._bound_driver(node)
            if GRAPHICS_NODE.search(node.name) or driver and driver.name in GRAPHICS_DRIVERS:
                self._add_graphics(devices, node, pci, driver=driver)
        for node in self._paths(self.sys_root / 'class/graphics', 'fb[0-9]*'):
            self._add_graphics(devices, node / 'device', pci, node.name)
        for node in self._paths(self.sys_root / 'bus/pci/devices', '*'):
            kind = (self.read(node / 'class') or '').strip()
            if re.fullmatch(r'0x03[0-9a-fA-F]{4}', kind):
                self._add_graphics(devices, node, pci)
        identifiers = {item.identifier for item in devices.values()}
        for slot, identity in pci.items():
            if slot not in identifiers:
                devices[slot] = identity
        gpus, displays = [], []
        has_v3d = any(any(value.endswith('-v3d') for value in item.compatibles)
                      or item.driver and item.driver.name == 'v3d' for item in devices.values())
        for item in list(devices.values())[:MAX_DEVICES]:
            driver = item.driver.name if item.driver else ''
            vc4 = driver == 'vc4' or any(re.search(r'-vc[456]$', value) for value in item.compatibles)
            framebuffer_only = any(alias.startswith('fb') for alias in item.aliases) and not any(alias.startswith('renderD') for alias in item.aliases)
            display_only = driver in {'sun4i-drm', 'sun4i_drm', 'sunxi', 'simple-framebuffer', 'simpledrm', 'bcm2708_fb'}
            display_only |= any('display-engine' in value or 'simple-framebuffer' in value for value in item.compatibles)
            display_only |= vc4 and (has_v3d or not any(alias.startswith('renderD') for alias in item.aliases))
            (displays if display_only or framebuffer_only else gpus).append(item)
        board, soc = self._board_and_soc()
        modules = tuple(self._module_info(self.sys_root / 'module' / name, name)
                        for name in GRAPHICS_MODULES if (self.sys_root / 'module' / name).is_dir())
        return HardwareInfo(cpus, tuple(gpus), tuple(displays), board, soc,
                            _name(self.read(self.proc_root / 'sys/kernel/osrelease')) or '',
                            self._cpu_drivers(), modules)

    @staticmethod
    def _resolve(path: Path) -> Optional[Path]:
        try:
            return path.resolve(strict=True)
        except (OSError, RuntimeError):
            return None

    def _bound_driver(self, device: Path) -> Optional[DriverInfo]:
        link = device / 'driver'
        # Only an actual driver symlink establishes a binding. A module being
        # present or a device-tree compatible must not be mistaken for one.
        try:
            target = self._resolve(link) if link.is_symlink() else None
        except OSError:
            target = None
        if target is None:
            return None
        module = self._resolve(target / 'module')
        if module:
            info = self._module_info(module, target.name)
            return replace(info, source=str(link))
        return DriverInfo(target.name, str(link))

    def _module_info(self, module: Path, name: str) -> DriverInfo:
        return DriverInfo(name, str(module), module.name,
                          _name(self.read(module / 'version')),
                          _name(self.read(module / 'srcversion')))

    def _add_graphics(self, devices: dict[str, DeviceIdentity], device: Path,
                      pci: dict[str, DeviceIdentity], alias: str = '',
                      driver: Optional[DriverInfo] = None) -> None:
        canonical = self._resolve(device)
        if canonical is None:
            return
        key = str(canonical)
        if key in devices:
            item = devices[key]
            if alias and alias not in item.aliases:
                devices[key] = replace(item, aliases=(*item.aliases, alias))
            return
        driver = driver or self._bound_driver(device)
        compatibles = compatible_values(self.read(device / 'of_node/compatible'))
        identity = pci.get(canonical.name.lower()) or self._linux_gpu(device, canonical.name, compatibles)
        if identity is None:
            # Report the enumerated device, not an invented GPU model.
            identity = DeviceIdentity(f'{canonical.name} (model unavailable)', str(device), canonical.name)
        devices[key] = replace(identity, aliases=(alias,) if alias else (), driver=driver,
                               compatibles=compatibles)

    def _linux_gpu(self, device: Path, identifier: str,
                   compatibles: tuple[str, ...]) -> Optional[DeviceIdentity]:
        for leaf in ('product_name', 'label'):
            name = _name(self.read(device / leaf))
            if name:
                return DeviceIdentity(name, str(device / leaf), identifier)
        name = graphics_name(compatibles)
        if name:
            return DeviceIdentity(name, str(device / 'of_node/compatible'), identifier)
        vendor = (self.read(device / 'vendor') or '').strip()
        product = (self.read(device / 'device') or '').strip()
        if re.fullmatch(r'0x[0-9a-fA-F]{4}', vendor) and re.fullmatch(r'0x[0-9a-fA-F]{4}', product):
            return DeviceIdentity(f'PCI GPU {vendor[2:]}:{product[2:]} (model unavailable)',
                                  str(device) + ' · vendor/device IDs', identifier)
        return None

    def _board_and_soc(self) -> tuple[Optional[DeviceIdentity], Optional[DeviceIdentity]]:
        board = soc = None
        for root in (self.sys_root / 'firmware/devicetree/base', self.proc_root / 'device-tree'):
            model = _name(self.read(root / 'model'))
            compatibles = compatible_values(self.read(root / 'compatible'))
            if model and board is None:
                board = DeviceIdentity(model, str(root / 'model'), compatibles=compatibles)
            if soc is None:
                for value in compatibles:
                    match = re.fullmatch(r'allwinner,sun[0-9]+[a-z]-([a-z][0-9]+)', value)
                    broadcom = re.fullmatch(r'brcm,(bcm[0-9]+)', value)
                    if match or broadcom:
                        name = 'Allwinner ' + match[1].upper() if match else 'Broadcom ' + broadcom[1].upper()
                        soc = DeviceIdentity(name, str(root / 'compatible'), compatibles=compatibles)
                        break
        if soc is None:
            for node in self._paths(self.sys_root / 'devices', 'soc[0-9]*'):
                name = _name(self.read(node / 'soc_id'))
                family = _name(self.read(node / 'family'))
                if name:
                    soc = DeviceIdentity(f'{family} {name}' if family else name, str(node / 'soc_id'))
                    break
        return board, soc

    def _cpu_drivers(self) -> tuple[DriverInfo, ...]:
        root = self.sys_root / 'devices/system/cpu'
        bases = self._paths(root / 'cpufreq', 'policy[0-9]*')
        bases += [node / 'cpufreq' for node in self._paths(root, 'cpu[0-9]*')]
        found = {}
        for base in bases:
            path = base / 'scaling_driver'
            name = _name(self.read(path))
            if name and name not in found:
                found[name] = DriverInfo(name, str(path))
        return tuple(found.values())
