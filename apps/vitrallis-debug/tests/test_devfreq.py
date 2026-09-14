import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from devfreq import DevfreqMonitor, parse_event
from diagnostics import GpuCollector


def event(stamp, load, device='1c40000.gpu', interval=50):
    return (' worker-10 [000] .... %0.6f: devfreq_monitor: dev_name=%-30s '
            'freq=384000000    polling_ms=%-3s load=%s\n' % (stamp, device, interval, load)).encode()


class DevfreqTests(unittest.TestCase):
    def test_kernel_format_and_malformed_load(self):
        self.assertEqual(parse_event(event(10, 72).decode()), ('1c40000.gpu', 10, 50, 72))
        for value in ('nan', '-1', '101', '1.2', '50 trailing'):
            self.assertIsNone(parse_event(event(10, value).decode()))
        self.assertIsNone(parse_event(event(10, 50, interval=0).decode()))
        self.assertIsNone(parse_event('freq=384000000'))
        self.assertIsNone(parse_event(event(10, '9' * 5000).decode()))

    def test_two_second_weighted_average_and_stale_samples(self):
        now = [10.0]
        monitor = DevfreqMonitor(clock=lambda: now[0])
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        self.addCleanup(os.close, write_fd)
        self.addCleanup(monitor.close)
        monitor.fd = read_fd
        monitor.instance = Path('/nonexistent/test-instance')
        os.write(write_fd, event(9.5, 20, interval=50) + event(10, 80, interval=150))
        reading = monitor.collect({'1c40000.gpu'})
        self.assertEqual(reading[:2], ('1c40000.gpu', 65))
        self.assertEqual(monitor.collect({'1c40000.gpu'})[1], 65)  # no duplicate read
        now[0] = 12.1
        self.assertIsNone(monitor.collect({'1c40000.gpu'}))
        os.write(write_fd, event(12.1, 0))
        self.assertEqual(monitor.collect({'1c40000.gpu'})[1], 0)

    def test_partial_lines_device_filter_duplicate_and_clock_bounds(self):
        monitor = DevfreqMonitor()
        line = event(10, 50)
        monitor.ingest(line[:30], {'1c40000.gpu'}, 10)
        self.assertFalse(monitor.samples)
        monitor.ingest(line[30:] + line + event(10, 99, device='memory-controller')
                       + event(20, 100) + event(1, 10), {'1c40000.gpu'}, 10)
        self.assertEqual(list(monitor.samples), ['1c40000.gpu'])
        self.assertEqual(len(monitor.samples['1c40000.gpu']), 1)
        monitor.ingest(b'', set(), 10)
        self.assertFalse(monitor.samples)

    def test_denied_instance_creation_does_not_modify_global_tracing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            enable = root / 'kernel/tracing/events/devfreq/devfreq_monitor/enable'
            enable.parent.mkdir(parents=True)
            enable.write_text('0')
            monitor = DevfreqMonitor(root)
            with patch.object(Path, 'mkdir', side_effect=PermissionError('denied')):
                self.assertIsNone(monitor.collect({'1c40000.gpu'}))
            self.assertEqual(enable.read_text(), '0')
            self.assertIn('delegated', monitor.reason)
            monitor.close()

    def test_collector_matches_devfreq_device_and_excludes_frequency_only_nodes(self):
        with tempfile.TemporaryDirectory() as temporary, patch('diagnostics.shutil.which', return_value=None):
            root = Path(temporary)
            (root / 'class/devfreq/1c40000.gpu').mkdir(parents=True)
            (root / 'class/devfreq/memory').mkdir()
            collector = GpuCollector(root)
            with patch.object(collector.monitor, 'collect', return_value=('1c40000.gpu', 45, 'trace · 2 s average')) as collect:
                self.assertEqual(collector.collect().percent, 45)
                collect.assert_called_once_with({'1c40000.gpu'})
            collector.close()

    def test_close_prevents_reopening(self):
        monitor = DevfreqMonitor()
        monitor.close()
        with patch.object(monitor, '_start') as start:
            self.assertIsNone(monitor.collect({'1c40000.gpu'}))
            start.assert_not_called()

    def test_private_instance_setup_and_cleanup_leave_global_event_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracing = root / 'kernel/tracing'
            enable = tracing / 'events/devfreq/devfreq_monitor/enable'
            enable.parent.mkdir(parents=True)
            enable.write_text('0')
            (tracing / 'instances').mkdir()
            monitor = DevfreqMonitor(root, clock=lambda: 10)
            read_fd, write_fd = os.pipe()
            os.set_blocking(read_fd, False)
            self.addCleanup(os.close, write_fd)
            self.addCleanup(monitor.close)
            writes = []
            with patch.object(monitor, '_write', side_effect=lambda path, value: writes.append((path, value))), \
                    patch('devfreq.os.open', return_value=read_fd):
                self.assertIsNone(monitor.collect({'1c40000.gpu'}))
                instance = monitor.instance
                self.assertEqual(instance.parent, tracing / 'instances')
                os.write(write_fd, event(10, 70))
                self.assertEqual(monitor.collect({'1c40000.gpu'})[1], 70)
                monitor.close()
            self.assertTrue(all(path.is_relative_to(instance) for path, _ in writes))
            self.assertIn((instance / 'events/devfreq/devfreq_monitor/enable', '1'), writes)
            self.assertIn((instance / 'events/devfreq/devfreq_monitor/enable', '0'), writes)
            self.assertFalse(instance.exists())
            self.assertEqual(enable.read_text(), '0')
            with self.assertRaises(OSError):
                os.fstat(read_fd)
