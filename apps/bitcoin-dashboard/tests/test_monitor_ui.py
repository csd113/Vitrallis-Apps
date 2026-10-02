from http.client import IncompleteRead
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor_ui import Monitor
import monitor_ui
from monitor import network_snapshot

ADDRESS = '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'
BLOCKS = [{'height': 966271, 'timestamp': int(time.time()), 'tx_count': 3200, 'size': 1500000}]
FEES = dict(fastestFee=3, halfHourFee=2, hourFee=1, economyFee=1, minimumFee=1)
POOL = dict(count=1200, vsize=1234567)
BALANCE = dict(chain_stats=dict(funded_txo_sum=123456789, spent_txo_sum=0),
               mempool_stats=dict(funded_txo_sum=0, spent_txo_sum=20))


class MonitorUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk(); self.root.geometry('480x272')
        self.app = Mock(root=self.root)
        self.fetch = Mock(side_effect=[BLOCKS, FEES, POOL, BALANCE, []])
        with patch.object(monitor_ui, 'load_watch', return_value=[dict(label='Genesis', address=ADDRESS)]):
            self.monitor = Monitor(self.app, self.fetch)
        self.addCleanup(self.cleanup)
        self.root.update()

    def cleanup(self):
        self.monitor.close(); self.root.destroy()

    def test_snapshot_parsing_rejects_bad_fields(self):
        self.assertEqual(network_snapshot(Mock(side_effect=[BLOCKS, FEES, POOL]))['height'], 966271)
        for bad in (True, -1, '3', 1.5):
            with self.assertRaises(ValueError):
                network_snapshot(Mock(side_effect=[BLOCKS, dict(FEES, fastestFee=bad), POOL]))

    def test_worker_cache_refresh_and_errors(self):
        self.monitor.worker(self.monitor.watches[0]); self.monitor.poll()
        self.assertEqual(self.monitor.cache[ADDRESS]['confirmed'], 123456789)
        self.assertEqual(self.monitor.failures, 0)
        self.assertIn('mempool.space', self.monitor.notice)
        self.assertGreater(self.monitor.next_refresh, time.monotonic()+290)
        self.fetch.reset_mock(); self.fetch.side_effect = TimeoutError(); self.monitor.refresh(True)
        self.assertTrue(self.monitor.busy)
        deadline = time.monotonic()+2
        while self.monitor.busy and time.monotonic() < deadline:
            self.monitor.poll(); self.root.update(); time.sleep(.01)
        self.monitor.busy = False
        for failure in (TimeoutError(), OSError(), ValueError(), IncompleteRead(b'partial')):
            self.monitor.fetch = Mock(side_effect=failure)
            self.monitor.worker(self.monitor.watches[0]); self.monitor.poll()
            self.assertEqual(self.monitor.cache[ADDRESS]['confirmed'], 123456789)
            self.assertGreater(self.monitor.failures, 0)
        self.monitor.fetch.reset_mock()
        self.monitor.refresh(True)
        self.monitor.fetch.assert_not_called()  # Failed requests respect backoff even with R.

    def test_partial_watch_refresh_never_publishes_incomplete_cache(self):
        self.monitor.cache[ADDRESS] = {'confirmed': 50, 'unconfirmed': 0,
                                      'transactions': [], 'updated': time.time()}
        self.monitor.fetch = Mock(side_effect=[BLOCKS, FEES, POOL, BALANCE, TimeoutError()])
        self.monitor.worker(self.monitor.watches[0])
        self.monitor.poll()
        self.assertEqual(self.monitor.cache[ADDRESS]['confirmed'], 50)
        self.assertIn('cached values retained', self.monitor.notice)
        self.assertEqual(self.monitor.network['height'], 966271)

    def test_tls_failure_reports_certificate_configuration(self):
        from urllib.error import URLError
        import ssl
        self.monitor.fetch = Mock(side_effect=URLError(ssl.SSLCertVerificationError()))
        self.monitor.worker(self.monitor.watches[0])
        self.monitor.poll()
        self.assertIn('check clock / certificates', self.monitor.notice)

    def test_keyboard_form_save_and_cancel_and_bounds(self):
        self.monitor.show('watch'); self.monitor.edit(False)
        entries = [child for child in self.monitor.content.winfo_children() if isinstance(child, tk.Entry)]
        entries[0].insert(0, 'Second')
        entries[1].insert(0, 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4')
        save = next(child for child in self.monitor.content.winfo_children() if isinstance(child, tk.Button) and child.cget('text') == 'Save')
        with patch.object(monitor_ui, 'save_watch') as write, patch.object(self.monitor, 'refresh'):
            save.focus_force(); self.root.update(); save.event_generate('<Return>'); self.root.update()
        self.assertEqual(len(self.monitor.watches), 2)
        write.assert_called_once()
        self.root.update()
        for child in self.monitor.content.winfo_children():
            self.assertGreaterEqual(child.winfo_x(), 0)
            self.assertLessEqual(child.winfo_x()+child.winfo_width(), 464)
            self.assertLessEqual(child.winfo_y()+child.winfo_height(), 190)
        self.monitor.remove()
        self.assertTrue(self.monitor.delete_pending)
        with patch.object(monitor_ui, 'save_watch', side_effect=OSError()): self.monitor.remove()
        self.assertEqual(len(self.monitor.watches), 2)

    def test_slow_worker_keeps_tk_responsive_and_single_inflight(self):
        started, release = threading.Event(), threading.Event()
        def slow(endpoint, base):
            started.set(); release.wait(2)
            raise TimeoutError()
        self.monitor.fetch = slow
        self.monitor.refresh(True)
        self.assertTrue(started.wait(1))
        self.monitor.refresh(True)
        self.assertTrue(self.monitor.busy)
        flag = []
        self.root.after_idle(lambda: flag.append(True)); self.root.update()
        self.assertEqual(flag, [True])
        self.monitor.show('watch')
        release.set()
        deadline = time.monotonic()+2
        while self.monitor.events.empty() and time.monotonic() < deadline: time.sleep(.01)
        self.monitor.poll()
        self.assertFalse(self.monitor.busy)
