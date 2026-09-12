import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import diagnostics as d


class CpuTests(unittest.TestCase):
    def test_initial_sample_then_utilization_without_guest_double_count(self):
        tracker = d.CpuTracker()
        self.assertEqual(tracker.update("cpu  10 2 3 80 1 2 1 1 99 99\ncpu0 1 0 1 8\n")[0], None)
        overall, cores = tracker.update("cpu  20 4 6 90 2 3 2 2 999 999\ncpu0 3 1 2 9\n")
        self.assertAlmostEqual(overall, 62.1)
        self.assertIsNotNone(cores["cpu0"])

    def test_counter_reset_and_invalid_delta_are_unavailable(self):
        before = d.CpuTimes(50, 100)
        self.assertIsNone(d.utilization(before, d.CpuTimes(40, 90)))
        self.assertIsNone(d.utilization(before, d.CpuTimes(120, 110)))
        self.assertIsNone(d.utilization(None, d.CpuTimes(1, 2)))

    def test_frequency_prefers_measured_and_labels_scaling_fallback(self):
        files = {
            "/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_cur_freq": "1200000\n",
            "/sys/devices/system/cpu/cpufreq/policy1/scaling_cur_freq": "800000\n",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "devices/system/cpu/cpufreq/policy0").mkdir(parents=True); (root / "devices/system/cpu/cpufreq/policy1").mkdir(parents=True)
            read = lambda path: files.get(str(path).replace(temp, "/sys"))
            first, all_values = d.discover_frequency(root, read_text=read)
        self.assertEqual(first.mhz, 1200.0)
        self.assertEqual(first.source, "measured")
        self.assertEqual(all_values[1].source, "driver-reported/requested")

    def test_frequency_cpuinfo_fallback_and_missing(self):
        value, values = d.discover_frequency(Path("/missing"), "cpu MHz : 456.7\n", lambda _: None)
        self.assertEqual(value.mhz, 456.7); self.assertEqual(values[0].path, "/proc/cpuinfo")
        self.assertEqual(d.discover_frequency(Path("/missing"), None, lambda _: None), (None, []))

    def test_load_and_uptime_parsing_rejects_bad_values(self):
        self.assertEqual(d.parse_load_averages("0.12 0.34 0.56 1/2 3"), (0.12, 0.34, 0.56))
        self.assertIsNone(d.parse_load_averages("nan 0 0"))
        self.assertEqual(d.parse_uptime("3600.5 1.2"), 3600.5)
        self.assertIsNone(d.parse_uptime("-1 0"))


class MemoryTemperatureTests(unittest.TestCase):
    def test_memory_available_and_estimated_fallback(self):
        exact = d.parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 600 kB\nMemFree: 10 kB\n")
        self.assertEqual((exact.used_kib, exact.percent, exact.estimated), (400, 40.0, False))
        fallback = d.parse_meminfo("MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 100 kB\nCached: 200 kB\nSReclaimable: 50 kB\nShmem: 10 kB\n")
        self.assertEqual((fallback.available_kib, fallback.estimated), (440, True))
        self.assertIsNone(d.parse_meminfo("MemTotal: 0 kB\nMemFree: 1 kB\n"))

    def test_sensor_selects_identified_and_rejects_bad_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); thermal = root / "class/thermal/thermal_zone0"; thermal.mkdir(parents=True)
            hwmon = root / "class/hwmon/hwmon0"; hwmon.mkdir(parents=True)
            values = {str(thermal / "type"): "battery", str(thermal / "temp"): "25000", str(hwmon / "name"): "cpu_thermal", str(hwmon / "temp1_input"): "41000", str(hwmon / "temp1_label"): "SoC"}
            (hwmon / "temp1_input").touch()
            sensors = d.discover_sensors(root, lambda path: values.get(str(path)))
        self.assertEqual(len(sensors), 2)
        self.assertEqual(next(item for item in sensors if item.selected).label, "SoC")
        self.assertIsNone(d._temperature("nan")); self.assertIsNone(d._temperature("999999"))


class NetworkTests(unittest.TestCase):
    def test_default_route_multiple_interfaces_and_ipv6_only(self):
        addresses = '[{"ifname":"lo","operstate":"UNKNOWN","addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8}]},{"ifname":"usb0","operstate":"UP","addr_info":[{"family":"inet6","local":"2001:db8::1","prefixlen":64}]}]'
        routes = '[{"dst":"default","gateway":"2001:db8::ff","dev":"usb0"}]'
        network = d.parse_network(addresses, routes, "chip")
        self.assertEqual(network.primary.name, "usb0")
        self.assertEqual(network.gateway, "2001:db8::ff")
        self.assertIn("2001:db8::1/64", network.primary.addresses_v6)

    def test_malformed_and_loopback_only_are_safe(self):
        self.assertEqual(d.parse_network("not json", None, "host").interfaces, ())
        loopback = d.parse_network('[{"ifname":"lo","operstate":"UP","addr_info":[]}]', None, "host")
        self.assertIsNone(loopback.primary)

    def test_collector_handles_missing_command(self):
        values = {"/proc/stat": "cpu 1 0 0 1\n", "/proc/cpuinfo": "", "/proc/meminfo": "MemTotal: 1 kB\nMemAvailable: 1 kB\n"}
        collector = d.SystemCollector(Path("/proc"), Path("/sys"), lambda _: None, lambda path: values.get(str(path)), lambda: 1.0)
        result = collector.collect()
        self.assertIn("network", result.errors)
        self.assertIsNone(result.network)


class HistoryTests(unittest.TestCase):
    def test_history_is_bounded_and_ignores_missing(self):
        history = d.History(2); history.add(None); history.add(1); history.add(2); history.add(3)
        self.assertEqual(history.items(), (2, 3))
