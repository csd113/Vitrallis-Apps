from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware import DeviceIdentity, HardwareCollector, HardwareInfo, DriverInfo, MAX_OUTPUT, linux_cpu_names, parse_lspci, run_probe


PCI = '''Slot:\t0000:01:00.0
Class:\tVGA compatible controller [0300]
Vendor:\tNVIDIA Corporation [10de]
Device:\tGA106 [GeForce RTX 3060] [2503]

Slot:\t0000:02:00.0
Class:\t3D controller [0302]
Vendor:\tAdvanced Micro Devices, Inc. [AMD/ATI] [1002]
Device:\tNavi 23 [Radeon RX 6600] [73ff]

Slot:\t0000:00:01.0
Class:\tHost bridge [0600]
Vendor:\tIntel Corporation [8086]
Device:\tHost [1234]
'''


class HardwareTests(unittest.TestCase):
    def test_linux_cpu_prefers_model_over_numeric_processor_and_board(self):
        names = linux_cpu_names('processor : 0\nHardware : Board Name\nmodel name : AMD Ryzen 7 7700\n\nprocessor : 1\nmodel name : AMD Ryzen 7 7700\n')
        self.assertEqual([item.name for item in names], ['AMD Ryzen 7 7700'])
        self.assertEqual(linux_cpu_names('processor : 0\nHardware : Board Name'), ())
        self.assertEqual(linux_cpu_names('Processor : ARMv7 Processor rev 2')[0].name, 'ARMv7 Processor rev 2')

    def test_linux_pci_parser_only_lists_display_devices(self):
        devices = parse_lspci(PCI)
        self.assertEqual(set(devices), {'0000:01:00.0', '0000:02:00.0'})
        self.assertIn('GeForce RTX 3060', devices['0000:01:00.0'].name)
        self.assertNotIn('[2503]', devices['0000:01:00.0'].name)
        self.assertEqual(parse_lspci('Slot:\t../../evil\nClass:\tVGA [0300]\nDevice:\tGPU'), {})

    def test_linux_drm_and_render_node_deduplicate_and_match_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = root / 'sys/devices/pci0000:00/0000:01:00.0'
            device.mkdir(parents=True)
            for alias in ('card0', 'renderD128'):
                node = root / 'sys/class/drm' / alias
                node.mkdir(parents=True)
                (node / 'device').symlink_to(device, target_is_directory=True)
            runner = Mock(return_value=PCI)
            collector = HardwareCollector(root/'proc', root/'sys', runner=runner)
            result = collector.collect()
            self.assertEqual(len(result.gpus), 2)
            self.assertIn('card0', result.gpus[0].aliases)
            self.assertIn('renderD128', result.gpus[0].aliases)
            self.assertIn('RTX 3060', result.gpu_name('card0'))
            self.assertIn('+1 more', result.gpu_name())
            self.assertIs(collector.collect(), result)
            self.assertEqual(runner.call_count, 1)

    def test_embedded_cpu_and_gpu_use_device_tree_without_drm_or_pciutils(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cpu = root/'sys/firmware/devicetree/base/cpus/cpu@0'
            cpu.mkdir(parents=True)
            (cpu/'compatible').write_text('arm,cortex-a8\x00')
            gpu = root/'sys/bus/platform/devices/1c40000.gpu/of_node'
            gpu.mkdir(parents=True)
            (gpu/'compatible').write_text('arm,mali-400\x00')
            result = HardwareCollector(root/'proc', root/'sys', runner=lambda _: None).collect()
            self.assertEqual(result.cpu_name, 'ARM Cortex-A8')
            self.assertEqual(result.gpu_name(), 'ARM Mali-400')

    def test_linux_pci_ids_remain_available_without_model_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = root/'sys/bus/pci/devices/0000:04:00.0'
            device.mkdir(parents=True)
            for leaf, value in (('class', '0x030000'), ('vendor', '0x1002'), ('device', '0x73ff')):
                (device/leaf).write_text(value)
            result = HardwareCollector(root/'proc', root/'sys', runner=lambda _: None).collect()
            self.assertEqual(len(result.gpus), 1)
            self.assertIn('1002:73ff', result.gpu_name())
            self.assertIn('model unavailable', result.gpu_name())

    def test_no_probing_until_collection_and_missing_sources_are_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runner = Mock(return_value=None)
            collector = HardwareCollector(root/'proc', root/'sys', runner=runner)
            runner.assert_not_called()
            self.assertEqual(collector.collect(), HardwareInfo())
            collector.collect()
            self.assertEqual(runner.call_count, 1)

    def test_gpu_matching_does_not_mislabel_unrelated_counter(self):
        info = HardwareInfo(gpus=(DeviceIdentity('AMD Radeon', '/sys', 'pci:one', ('card0',)),))
        self.assertEqual(info.gpu_name('card0'), 'AMD Radeon')
        self.assertEqual(info.gpu_name('card1'), 'card1')

    def test_probe_output_unicode_failure_and_size_limit(self):
        self.assertEqual(run_probe([sys.executable, '-c', 'print("CPU / GPU")']), 'CPU / GPU\n')
        self.assertIsNone(run_probe([sys.executable, '-c', 'raise SystemExit(1)']))
        self.assertIsNone(run_probe([sys.executable, '-c', f'import sys; sys.stdout.write("x"*{MAX_OUTPUT+1})']))
        self.assertIsNone(run_probe(['/vitrallis/no-such-program']))

    def test_timed_out_probe_is_killed(self):
        process = Mock()
        process.stdout.read.return_value = b''
        process.wait.side_effect = [subprocess.TimeoutExpired('probe', 8), 0]
        with patch('hardware.subprocess.Popen', return_value=process):
            self.assertIsNone(run_probe(['probe']))
        process.kill.assert_called_once()
        process.wait.assert_any_call(timeout=8)
        process.stdout.close.assert_called_once()


class EmbeddedDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc, self.sys = self.root/'proc', self.root/'sys'
        self.put(self.proc/'sys/kernel/osrelease', '6.12.20-test')

    @staticmethod
    def put(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def device(self, name, compatibles='', driver=None, module=None, version=None, aliases=()):
        node = self.sys/'devices/platform'/name
        node.mkdir(parents=True, exist_ok=True)
        if compatibles:
            self.put(node/'of_node/compatible', compatibles)
        platform = self.sys/'bus/platform/devices'/name
        platform.parent.mkdir(parents=True, exist_ok=True)
        platform.symlink_to(node, target_is_directory=True)
        if driver:
            target = self.sys/'bus/platform/drivers'/driver
            target.mkdir(parents=True, exist_ok=True)
            (node/'driver').symlink_to(target, target_is_directory=True)
            if module:
                mod = self.sys/'module'/module
                mod.mkdir(parents=True, exist_ok=True)
                (target/'module').symlink_to(mod, target_is_directory=True)
                if version:
                    self.put(mod/'version', version)
                self.put(mod/'srcversion', 'ABC123')
        for alias in aliases:
            path = self.sys/('class/graphics' if alias.startswith('fb') else 'class/drm')/alias
            path.mkdir(parents=True, exist_ok=True)
            (path/'device').symlink_to(node, target_is_directory=True)
        return node

    def collect(self):
        return HardwareCollector(self.proc, self.sys, runner=lambda _: None).collect()

    def board(self, name, compatibles, cpu):
        dt = self.sys/'firmware/devicetree/base'
        self.put(dt/'model', name+'\x00')
        self.put(dt/'compatible', compatibles)
        self.put(dt/'cpus/cpu@0/compatible', cpu+'\x00')

    def test_pi4_v3d_and_vc4_report_separate_bindings(self):
        self.board('Raspberry Pi 4 Model B', 'raspberrypi,4-model-b\x00brcm,bcm2711\x00', 'arm,cortex-a72')
        self.device('gpu', 'brcm,bcm2711-vc5\x00', 'vc4', 'vc4', aliases=('card0',))
        self.device('fec00000.v3d', 'brcm,2711-v3d\x00', 'v3d', 'v3d', aliases=('card1', 'renderD128'))
        self.put(self.sys/'devices/system/cpu/cpufreq/policy0/scaling_driver', 'cpufreq-dt\n')
        info = self.collect()
        self.assertEqual(info.board.name, 'Raspberry Pi 4 Model B')
        self.assertEqual(info.soc.name, 'Broadcom BCM2711')
        self.assertEqual(info.cpu_name, 'ARM Cortex-A72')
        self.assertEqual(len(info.gpus), 1)
        self.assertEqual(len(info.displays), 1)
        self.assertEqual(info.gpus[0].driver.name, 'v3d')
        self.assertEqual(info.displays[0].driver.name, 'vc4')
        self.assertEqual(info.gpus[0].aliases, ('card1', 'renderD128'))
        self.assertEqual(info.gpu_name('card1'), 'Broadcom V3D (2711-v3d)')
        self.assertIsNone(info.gpus[0].driver.version)
        self.assertEqual(info.kernel_release, '6.12.20-test')
        self.assertEqual(info.cpu_drivers[0].name, 'cpufreq-dt')

    def test_pi5_binding_and_builtin_driver_without_module_version(self):
        self.board('Raspberry Pi 5 Model B', 'raspberrypi,5-model-b\x00brcm,bcm2712\x00', 'arm,cortex-a76')
        self.device('1002000000.v3d', 'brcm,2712-v3d\x00', 'v3d', aliases=('card1', 'renderD128'))
        info = self.collect()
        self.assertEqual(info.soc.name, 'Broadcom BCM2712')
        self.assertEqual(info.gpus[0].driver.name, 'v3d')
        self.assertIsNone(info.gpus[0].driver.module)
        self.assertIsNone(info.gpus[0].driver.version)

    def test_pi3_vc4_render_node_is_a_gpu_without_separate_v3d(self):
        self.device('gpu', 'brcm,bcm2835-vc4\x00', 'vc4', 'vc4', aliases=('card0', 'renderD128'))
        info = self.collect()
        self.assertEqual(len(info.gpus), 1)
        self.assertEqual(info.gpus[0].driver.name, 'vc4')
        self.assertFalse(info.displays)

    def test_pi3_component_v3d_does_not_double_count_vc4_wrapper(self):
        self.device('gpu', 'brcm,bcm2835-vc4\x00', 'vc4', aliases=('card0', 'renderD128'))
        self.device('3fc00000.v3d', 'brcm,bcm2835-v3d\x00', 'vc4_v3d')
        info = self.collect()
        self.assertEqual(len(info.gpus), 1)
        self.assertEqual(info.gpus[0].driver.name, 'vc4_v3d')
        self.assertEqual(len(info.displays), 1)

    def test_pocketchip_r8_lima_and_display_driver(self):
        self.board('NextThing C.H.I.P.', 'nextthing,chip\x00allwinner,sun5i-r8\x00allwinner,sun5i-a13\x00', 'arm,cortex-a8')
        self.put(self.proc/'cpuinfo', 'processor : 0\nmodel name : ARMv7 Processor rev 2 (v7l)\n')
        self.device('display-engine', 'allwinner,sun5i-a13-display-engine\x00', 'sun4i-drm', 'sun4i_drm', aliases=('card0', 'fb0'))
        self.device('1c40000.gpu', 'allwinner,sun5i-a13-mali\x00arm,mali-400\x00', 'lima', 'lima', aliases=('card1', 'renderD128'))
        self.put(self.sys/'devices/system/cpu/cpu0/cpufreq/scaling_driver', 'sunxi-cpufreq')
        info = self.collect()
        self.assertEqual(info.soc.name, 'Allwinner R8')
        self.assertEqual(info.cpu_name, 'ARM Cortex-A8')
        self.assertEqual(info.gpu_name(), 'ARM Mali-400')
        self.assertEqual(len(info.gpus), 1)
        self.assertEqual(info.gpus[0].driver.name, 'lima')
        self.assertEqual(info.displays[0].driver.name, 'sun4i-drm')
        self.assertEqual(info.cpu_drivers[0].name, 'sunxi-cpufreq')

    def test_non_graphics_sunxi_platform_device_is_not_a_gpu(self):
        self.device('sunxi-cpufreq', driver='sunxi-cpufreq')
        self.assertFalse(self.collect().gpus)

    def test_legacy_mali_is_found_even_when_display_drm_exists(self):
        self.device('display-engine', 'allwinner,sun5i-a13-display-engine\x00', 'sun4i-drm', aliases=('card0',))
        self.device('mali.0', driver='mali', module='mali', version='r3p0')
        info = self.collect()
        self.assertEqual(len(info.gpus), 1)
        self.assertEqual(info.gpus[0].driver.name, 'mali')
        self.assertEqual(info.gpus[0].driver.version, 'r3p0')
        self.assertEqual(info.gpus[0].driver.srcversion, 'ABC123')
        self.assertIn('model unavailable', info.gpus[0].name)

    def test_unbound_mali_does_not_use_loaded_module_as_binding(self):
        self.device('1c40000.gpu', 'arm,mali-400\x00')
        self.put(self.sys/'module/lima/version', 'present-but-not-bound')
        info = self.collect()
        self.assertIsNone(info.gpus[0].driver)
        self.assertEqual(info.graphics_modules[0].name, 'lima')
        self.assertEqual(info.graphics_modules[0].version, 'present-but-not-bound')

    def test_broken_driver_link_does_not_crash_or_invent_version(self):
        device = self.device('1c40000.gpu', 'arm,mali-400\x00')
        (device/'driver').symlink_to(self.sys/'missing-driver')
        self.assertIsNone(self.collect().gpus[0].driver)

    def test_proc_device_tree_fallback_and_absent_soc(self):
        self.put(self.proc/'device-tree/model', 'Raspberry Pi (fixture)\x00')
        self.put(self.proc/'device-tree/compatible', 'raspberrypi,unknown\x00')
        self.put(self.proc/'device-tree/cpus/cpu@0/compatible', 'arm,cortex-a53\x00')
        info = self.collect()
        self.assertEqual(info.cpu_name, 'ARM Cortex-A53')
        self.assertEqual(info.board.name, 'Raspberry Pi (fixture)')
        self.assertIsNone(info.soc)
