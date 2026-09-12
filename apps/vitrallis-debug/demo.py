"""Explicit deterministic data for visual checks; never used by normal startup."""
from __future__ import annotations

import time

from diagnostics import Frequency, Memory, Network, NetworkInterface, Snapshot, TemperatureSensor


class DemoCollector:
    """Fixture collector for screenshots and desktop UI verification only."""
    def collect(self, include_network: bool = True) -> Snapshot:
        network = Network(
            "pocketchip-demo",
            (NetworkInterface("wlan-demo", "UP", ("192.168.17.42/24",), ("2001:db8:20:17::4242/64",), 1_024_000, 512_000),
             NetworkInterface("usb0", "DOWN", (), (), 0, 0),
             NetworkInterface("lo", "UNKNOWN", ("127.0.0.1/8",), ("::1/128",))),
            "wlan-demo", "192.168.17.1",
        ) if include_network else None
        sensor = TemperatureSensor("SoC thermal sensor", "cpu_thermal", 47.2,
                                   "/sys/class/thermal/thermal_zone9/temp", 95.0, True)
        return Snapshot(time.monotonic(), 37.4, {"cpu0": 31.2, "cpu1": 43.6},
                        "Allwinner R8 ARM Cortex-A8 demonstration CPU name", 1,
                        Frequency(1008.0, "measured", "/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq"),
                        [("policy0", 200.0, 1008.0)],
                        Memory(512_000, 280_000, 120_000, 20_000, 100_000, 0, 0), [sensor], network, {})
