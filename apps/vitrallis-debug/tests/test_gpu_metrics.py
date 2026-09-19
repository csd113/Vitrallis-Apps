import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gpu_metrics import LimaProvider, Records, Sample, State, TraceReader, lima_device, parse_sample


def record(load=31, device='1c40000.gpu', stamp=100.0):
    return f' worker-1 [000] ..... {stamp:.6f}: devfreq_monitor: dev_name={device} freq=297000000 polling_ms=50 load={load}\n'


class Metrics(unittest.TestCase):
    def test_parser_fields_and_zero(self):
        self.assertEqual(parse_sample(record()), Sample('1c40000.gpu', 297000000, 50, 31, 100.0))
        self.assertEqual(parse_sample(record(0)).load, 0)
        for line in ('', record(-1), record(101), record().replace('freq=297000000', 'freq=oops'),
                     record().replace('polling_ms=50', 'polling_ms=0'), record() + 'load=1',
                     record().replace('devfreq_monitor:', 'other:'), 'x' * 4097):
            self.assertIsNone(parse_sample(line), line)

    def test_stream_handles_partial_unrelated_oversized_and_bad_records(self):
        stream = Records('1c40000.gpu')
        line = record(0).encode()
        self.assertIsNone(stream.feed(line[:60]))
        self.assertEqual(stream.feed(line[60:]).load, 0)
        self.assertIsNone(stream.feed(record(device='memory').encode()))
        self.assertIsNone(stream.feed(b'x' * 5000))
        self.assertIsNone(stream.feed(line))  # remainder of oversized line
        self.assertEqual(stream.feed(b'malformed\n' + line).load, 0)
        self.assertLessEqual(len(stream.pending), 4096)

    def fixture(self, root, devfreq=True):
        device = root / 'devices/platform/soc/1c40000.gpu'
        device.mkdir(parents=True)
        driver = root / 'bus/platform/drivers/lima'
        driver.mkdir(parents=True)
        (device / 'driver').symlink_to(driver)
        (driver / device.name).symlink_to(device)
        cards = root / 'class/drm'
        cards.mkdir(parents=True)
        (cards / 'card0').mkdir()  # unbound display must not abort GPU discovery
        (cards / 'card1').mkdir()
        (cards / 'card1/device').symlink_to(device)
        if devfreq:
            path = device / 'devfreq' / device.name
            path.mkdir(parents=True)
            (path / 'cur_freq').write_text('297000000\n')
            (root / 'class/devfreq').mkdir()
            (root / 'class/devfreq' / device.name).symlink_to(path)
        return device

    def test_lima_detection_matches_real_device_not_card_number(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "class/devfreq/000-broken").symlink_to(root / "missing")
            device = lima_device(root)
            self.assertEqual(device.name, '1c40000.gpu')
            self.assertEqual(device.driver, 'Lima')
            self.assertIsNotNone(device.devfreq)

    def test_distinct_unavailable_states_and_static_frequency(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = LimaProvider(root, reader_factory=lambda *_: (_ for _ in ()).throw(PermissionError()))
            self.assertIsNone(provider.collect())
            self.assertEqual(provider.state, State.UNSUPPORTED)
            self.fixture(root, devfreq=False)
            provider.next_discovery = 0
            self.assertIsNone(provider.collect())
            self.assertEqual(provider.state, State.MISSING_DEVFREQ)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            provider = LimaProvider(root, reader_factory=lambda *_: (_ for _ in ()).throw(PermissionError()))
            self.assertIsNone(provider.collect())
            self.assertEqual(provider.state, State.TRACE_UNAVAILABLE)
            self.assertEqual(provider.frequency_hz, 297000000)
            provider.close()
            self.assertIsNone(provider.collect())

    @unittest.skipUnless(sys.platform == 'linux', 'requires Linux FIFO flock semantics')
    def test_reader_zero_stale_and_prompt_join(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace_pipe'
            os.mkfifo(path)
            # Keep writer alive so the reader can block rather than see EOF.
            writer = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            reader = TraceReader(path, '1c40000.gpu')
            try:
                os.write(writer, record(0, stamp=time.monotonic()).encode())
                end = time.monotonic() + 1
                while reader.sample() is None and time.monotonic() < end:
                    time.sleep(.005)
                self.assertEqual(reader.sample().load, 0)
                reader.clock = lambda: time.monotonic() + 10
                self.assertIsNone(reader.sample())
            finally:
                start = time.monotonic()
                reader.close()
                os.close(writer)
            self.assertLess(time.monotonic() - start, .5)
            self.assertFalse(reader.thread.is_alive())
