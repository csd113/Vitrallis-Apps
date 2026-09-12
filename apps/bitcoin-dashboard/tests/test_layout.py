import time
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import tkinter as tk
import threading
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as bitcoin

class LayoutTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name in ('SETTINGS', 'CACHE'):
            patcher = patch.object(bitcoin, name, Path(directory.name) / (name + '.json'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_app(self):
        root = tk.Tk()
        with patch.object(bitcoin.App, 'refresh_all'):
            app = bitcoin.App(root)
        self.addCleanup(app.close)
        root.after_cancel(app.poll_id)
        app.poll_id = None
        app.next_fetch = app.next_chain = float('inf')
        root.update()
        return app

    def labels(self, app):
        return [app.canvas.itemcget(item, 'text') for item in app.canvas.find_all()
                if app.canvas.type(item) == 'text']

    def test_packaged_icon_loads_from_another_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                app = self.make_app()
                self.assertEqual((app.icon.width(), app.icon.height()), (128, 128))
            finally:
                os.chdir(previous)

    def assert_text_bounds(self, app):
        boxes = []
        for item in app.canvas.find_all():
            if app.canvas.type(item) != 'text':
                continue
            box = app.canvas.bbox(item)
            label = app.canvas.itemcget(item, 'text')
            self.assertGreaterEqual(box[0], 0, (label, box))
            self.assertGreaterEqual(box[1], 0, (label, box))
            self.assertLessEqual(box[2], app.canvas.winfo_width(), (label, box))
            self.assertLessEqual(box[3], app.canvas.winfo_height(), (label, box))
            for other, name in boxes:
                overlap = (min(box[2], other[2]) > max(box[0], other[0])
                           and min(box[3], other[3]) > max(box[1], other[1]))
                self.assertFalse(overlap, (label, box, name, other))
            boxes.append((box, label))

    def test_card_taps_open_each_detail_and_back_restores_selection(self):
        app = self.make_app()
        app.root.focus_force()
        with patch.object(bitcoin.threading, 'Thread') as thread:
            for index, (x1, y1, x2, y2) in enumerate(app.card_bounds()):
                x, y = (x1+x2)//2, (y1+y2)//2
                app.canvas.event_generate('<Button-1>', x=x, y=y)
                app.canvas.event_generate('<ButtonRelease-1>', x=x, y=y)
                app.root.update()
                self.assertEqual(app.detail_card, index)
                self.assertIn(bitcoin.CARD_TITLES[index], self.labels(app))
                self.assertEqual(app.home_button.cget('text'), 'Back')
                self.assertEqual(app.home_button.tk_focusNext(), app.refresh_button)
                app.home_button.event_generate('<Enter>')
                app.home_button.event_generate('<Button-1>', x=20, y=18)
                app.home_button.event_generate('<ButtonRelease-1>', x=20, y=18)
                app.root.update()
                self.assertIsNone(app.detail_card)
                self.assertEqual(app.selected_card, index)
                self.assertEqual(app.root.focus_get(), app.canvas)
                self.assertEqual(app.home_button.cget('text'), 'Home')
                self.assertTrue(app.canvas.find_withtag('card-selection'))
            thread.assert_not_called()

    def test_arrows_enter_escape_and_modal_settings_navigation(self):
        app = self.make_app()
        root = app.root
        root.focus_force()
        app.settings_button.focus_set()
        for key, expected in (('Right', 0), ('Right', 1), ('Down', 2), ('Right', 0),
                              ('Left', 2), ('Up', 1)):
            root.event_generate('<' + key + '>')
            root.update()
            self.assertEqual(app.selected_card, expected)
            self.assertEqual(root.focus_get(), app.canvas)
        root.event_generate('<Return>')
        root.update()
        self.assertEqual(app.detail_card, 1)
        self.assertEqual(root.focus_get(), app.home_button)
        root.event_generate('<Right>')
        root.update()
        self.assertEqual(app.detail_card, 1)
        app.toggle_settings()
        root.update()
        root.event_generate('<Left>')
        root.update()
        self.assertEqual(app.selected_card, 1)
        root.event_generate('<Escape>')
        root.update()
        self.assertIsNone(app.settings_panel)
        self.assertEqual(app.detail_card, 1)
        root.event_generate('<Escape>')
        root.update()
        self.assertIsNone(app.detail_card)
        self.assertEqual(root.focus_get(), app.canvas)
        root.event_generate('<KP_Enter>')
        root.update()
        self.assertEqual(app.detail_card, 1)
        app.toggle_settings()
        app.home_button.invoke()
        root.update()
        self.assertIsNone(app.settings_panel)
        self.assertIsNone(app.detail_card)
        self.assertFalse(app.closed)

    def test_drag_cancel_and_rapid_taps_do_not_stack_detail_views(self):
        app = self.make_app()
        app.canvas.event_generate('<Button-1>', x=60, y=180)
        app.canvas.event_generate('<ButtonRelease-1>', x=220, y=180)
        self.assertIsNone(app.detail_card)
        for _ in range(20):
            for _ in range(2):
                app.canvas.event_generate('<Button-1>', x=220, y=180)
                app.canvas.event_generate('<ButtonRelease-1>', x=220, y=180)
            self.assertEqual(app.detail_card, 1)
            app.escape()
            self.assertIsNone(app.detail_card)
            self.assertFalse(app.closed)
        app.toggle_settings()
        app.canvas.event_generate('<Button-1>', x=60, y=180)
        app.canvas.event_generate('<ButtonRelease-1>', x=60, y=180)
        self.assertIsNone(app.detail_card)

    def test_all_details_fit_loading_stale_and_extreme_data(self):
        app = self.make_app()
        now = time.time()
        normal = {'height': 966414, 'supply_sats': 2008210312500002,
                  'chain_updated': now, 'chain_gb': 767.309723, 'size_updated': now-86400}
        cases = ({}, normal, dict(normal, chain_updated=now-86400, size_updated=now-86400*8),
                 dict(normal, height=0, supply_sats=1, chain_gb=5e-324),
                 dict(normal, height=99999999, supply_sats=bitcoin.MAX_SUPPLY, chain_gb=1e9))
        for data in cases:
            for busy in (False, True):
                app.data = data
                app.chain_busy = busy
                for index in range(3):
                    with self.subTest(data=data, busy=busy, index=index):
                        app.open_card(index)
                        app.root.update()
                        self.assert_text_bounds(app)
                        if not data:
                            self.assertTrue(any(('Loading network data' if busy else 'Unavailable') in label
                                                for label in self.labels(app)))
                        app.back()
        app.data = normal
        app.chain_busy = False
        app.open_card(1)
        self.assertIn('20,082,103.12500002', self.labels(app))
        self.assertIn('2,008,210,312,500,002', self.labels(app))

    def test_detail_values_update_and_halving_remaining_is_not_off_by_one(self):
        app = self.make_app()
        now = time.time()
        app.data = {'height': 1049999, 'chain_updated': now, 'supply_sats': 2000000000000000}
        app.open_card(0)
        rows = dict(app.detail_rows()[0])
        self.assertEqual(rows['Block subsidy (BTC)'], '3.12500000')
        self.assertEqual(rows['Next halving at'], '1,050,000')
        self.assertEqual(rows['Blocks until halving'], '1')
        app.events.put(('chain', dict(app.data, height=1050000, chain_updated=now+1)))
        app.poll()
        self.assertIn('1.56250000', self.labels(app))
        self.assertIn('210,000', self.labels(app))
        app.back()
        self.assertIn('1,050,000', self.labels(app))

    def test_green_expires_at_ten_seconds_and_navigation_cannot_extend_it(self):
        app = self.make_app()
        app.data = {'height': 100, 'chain_updated': time.time()}
        app.events.put(('chain', dict(app.data, height=101)))
        with patch.object(bitcoin.time, 'monotonic', return_value=100):
            app.poll()
            self.assertEqual(app.highlight_until, 110)
            self.assertIsNotNone(app.highlight_id)
            self.assertTrue(app.canvas.find_withtag('block-highlight'))
        timer = app.highlight_id
        with patch.object(bitcoin.time, 'monotonic', return_value=109.999):
            app.open_card(0)
            app.back()
            app.events.put(('chain', dict(app.data)))
            app.poll()
            self.assertEqual(app.highlight_id, timer)
            self.assertEqual(app.highlight_until, 110)
            self.assertTrue(app.canvas.find_withtag('block-highlight'))
        with patch.object(bitcoin.time, 'monotonic', return_value=110):
            app.draw()
            self.assertFalse(app.canvas.find_withtag('block-highlight'))
        app.open_card(2)
        app.root.after_cancel(timer)
        app.expire_highlight()
        app.back()
        self.assertEqual(app.highlight_until, 0)
        self.assertIsNone(app.highlight_id)
        self.assertFalse(app.canvas.find_withtag('block-highlight'))

    def test_screen_bounds_and_no_overlapping_text(self):
        root = tk.Tk()
        try:
            with patch.object(bitcoin.App, 'refresh_all'), patch.object(bitcoin.App, 'poll'):
                app = bitcoin.App(root)
                root.update()
                now = time.time()
                cases = [
                    {},
                    {'price': 107740, 'updated': now, 'change': -.53,
                     'height': 966271, 'supply_sats': 2008210312500000, 'chain_updated': now,
                     'chain_gb': 767.1, 'size_updated': now-172800, 'size_fetched': now,
                     'points': [[now-86400, 108000], [now-40000, 109000], [now, 107740]]},
                    {'price': 999999.99, 'updated': now-3600, 'change': 99.99,
                     'height': 1234567, 'supply_sats': 2099999999900000, 'chain_updated': now-3600,
                     'chain_gb': 1234.5, 'size_updated': now-7*86400, 'size_fetched': now,
                     'points': [[now-86400, 50], [now-3600, 50]]}]
                for amount in (999999999999, 1e308, 5e-324):
                    cases.append(dict(cases[1], price=amount, change=amount,
                        height=99999999, supply_sats=bitcoin.MAX_SUPPLY,
                        chain_gb=1e9, points=[[now-86400, amount], [now, amount]]))
                for case in cases:
                    app.data = case
                    app.busy = app.chain_busy = False
                    app.draw(force=True)
                    root.update_idletasks()
                    boxes = []
                    for item in app.canvas.find_all():
                        if app.canvas.type(item) != 'text': continue
                        box = app.canvas.bbox(item)
                        label = app.canvas.itemcget(item, 'text')
                        self.assertGreaterEqual(box[0], 0, (label, box))
                        self.assertGreaterEqual(box[1], 0, (label, box))
                        self.assertLessEqual(box[2], 480, (label, box))
                        self.assertLessEqual(box[3], 272, (label, box))
                        for other, name in boxes:
                            overlap = min(box[2],other[2])-max(box[0],other[0]) > 0 and min(box[3],other[3])-max(box[1],other[1]) > 0
                            self.assertFalse(overlap, (label, box, name, other))
                        boxes.append((box,label))
                self.assertEqual(app.refresh_button.winfo_height(), 36)
        finally:
            root.destroy()

    def test_keyboard_focus_enter_space_back_and_rapid_navigation(self):
        app = self.make_app()
        root = app.root
        root.focus_force()
        app.settings_button.focus_set()
        app.settings_button.event_generate('<Return>')
        root.update()
        self.assertEqual(root.focus_get(), app.highlight_checkbox)
        original = app.highlight_enabled
        app.highlight_checkbox.event_generate('<space>')
        root.update()
        self.assertEqual(app.highlight_enabled, not original)
        app.highlight_checkbox.event_generate('<Return>')
        root.update()
        self.assertEqual(app.highlight_enabled, original)
        app.highlight_checkbox.event_generate('<Tab>')
        root.update()
        self.assertEqual(root.focus_get(), app.done_button)
        app.done_button.event_generate('<Tab>')
        root.update()
        self.assertEqual(root.focus_get(), app.highlight_checkbox)
        app.highlight_checkbox.event_generate('<Shift-Tab>')
        root.update()
        self.assertEqual(root.focus_get(), app.done_button)
        app.done_button.event_generate('<Return>')
        root.update()
        self.assertIsNone(app.settings_panel)
        self.assertEqual(root.focus_get(), app.settings_button)
        for _ in range(20):
            root.event_generate('<s>')
            root.update()
            self.assertIsNotNone(app.settings_panel)
            root.event_generate('<Escape>')
            root.update()
            self.assertIsNone(app.settings_panel)
        self.assertTrue(root.winfo_exists())
        self.assertEqual(app.settings_button.tk_focusNext(), app.home_button)
        self.assertEqual(app.home_button.tk_focusNext(), app.canvas)

    def test_settings_warning_and_save_failure_survive_reopening(self):
        bitcoin.SETTINGS.write_text('{bad')
        app = self.make_app()
        app.toggle_settings()
        self.assertIn('defaults used', app.settings_status.cget('text'))
        with patch.object(app, 'save_settings', return_value=False):
            app.highlight_checkbox.invoke()
        app.toggle_settings()
        app.toggle_settings()
        app.root.update()
        self.assertIn('could not save', app.settings_status.cget('text'))
        self.assertLessEqual(app.settings_status.winfo_reqwidth(), app.settings_panel.winfo_width()-24)

    def test_missing_and_failed_data_show_actionable_status(self):
        app = self.make_app()
        app.events.put(('done', 'Offline / connection error'))
        app.events.put(('chain_error', 'Offline / connection error'))
        app.events.put(('chart_error', 'Invalid CoinGecko data'))
        app.events.put(('chain_done', True))
        app.poll()
        labels = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_all()
                  if app.canvas.type(i) == 'text']
        self.assertIn('Offline / connection error · auto retry', labels)
        self.assertIn('Chart unavailable', labels)
        self.assertIn('Unavailable', labels)
        self.assertFalse(any('Loading' in text or 'Saved' in text or 'SAVED' in text for text in labels))

    def test_restart_restores_preferences_and_cache_then_requests_fresh_data(self):
        app = self.make_app()
        now = time.time()
        app.data = {'price': 100000, 'updated': now, 'change': None,
                    'height': 100, 'supply_sats': 5000000000, 'chain_updated': now}
        app.highlight_enabled = False
        self.assertTrue(app.save_settings())
        app.save_cache()
        app.close()
        root = tk.Tk()
        with patch.object(bitcoin.App, 'refresh_all') as refresh:
            restored = bitcoin.App(root)
        self.addCleanup(restored.close)
        self.assertEqual(restored.data, app.data)
        self.assertFalse(restored.highlight_enabled)
        self.assertEqual(restored.highlight_until, 0)
        refresh.assert_called_once_with()

    def test_thread_start_failure_recovers_and_resize_keeps_controls_visible(self):
        app = self.make_app()
        with patch.object(bitcoin.threading.Thread, 'start', side_effect=RuntimeError('unavailable')):
            app.refresh_all(True)
            app.poll()
        self.assertFalse(app.busy or app.chain_busy)
        self.assertEqual(app.message, 'Cannot start price refresh')
        self.assertEqual((app.failures, app.chain_failures), (1, 1))
        for dimensions in ('640x320', '480x272'):
            app.root.geometry(dimensions)
            app.root.update()
            app.draw()
            for widget in (app.refresh_button, app.settings_button, app.home_button):
                self.assertGreaterEqual(widget.winfo_x(), 0)
                self.assertLessEqual(widget.winfo_x()+widget.winfo_width(), app.root.winfo_width())
                self.assertEqual(widget.winfo_height(), 36)

    def test_poll_batches_cache_writes_and_rejects_older_samples(self):
        app = self.make_app()
        now = time.time()
        fresh = {'price': 100, 'updated': now, 'change': 0}
        app.events.put(('quote', fresh))
        app.events.put(('chain', {'height': 100, 'chain_updated': now, 'supply_sats': 5000000000}))
        app.events.put(('chart', [[now-100, 10], [now, 100]]))
        app.events.put(('size', {'chain_gb': 700, 'size_updated': now, 'size_fetched': now}))
        with patch.object(app, 'save_cache') as save:
            app.poll()
            save.assert_called_once()
        before = app.data.copy()
        app.events.put(('quote', dict(fresh, price=1, updated=now-1)))
        app.events.put(('chain', {'height': 99, 'chain_updated': now-1}))
        app.events.put(('chart', [[now-100, 10], [now-1, 1]]))
        app.events.put(('size', {'chain_gb': 1, 'size_updated': now-1, 'size_fetched': now}))
        with patch.object(app, 'save_cache') as save:
            app.poll()
            save.assert_not_called()
        self.assertEqual(app.data, before)
        app.data['price'] = 120
        app.draw()
        self.assertTrue(any(app.canvas.itemcget(i, 'text') == 'C$120.00'
                            for i in app.canvas.find_all() if app.canvas.type(i) == 'text'))
        with patch.object(app.canvas, 'delete') as delete:
            app.draw()
            delete.assert_not_called()

    def test_manual_refresh_deduplicates_and_respects_backoff(self):
        app = self.make_app()
        with patch.object(bitcoin.threading, 'Thread') as thread, \
             patch.object(bitcoin.time, 'monotonic', return_value=100):
            for _ in range(50):
                app.refresh_all(True)
            self.assertEqual(thread.call_count, 2)
            self.assertTrue(app.busy and app.chain_busy)
            app.events.put(('done', 'Rate limited'))
            app.events.put(('chain_done', True))
            app.poll()
            self.assertFalse(app.busy or app.chain_busy)
            self.assertEqual((app.next_fetch, app.next_chain), (340, 340))
            for _ in range(50):
                app.refresh_all(True)
            self.assertEqual(thread.call_count, 2)
            app.failures = app.chain_failures = 5
            app.events.put(('done', 'Rate limited'))
            app.events.put(('chain_done', True))
            app.poll()
            self.assertEqual((app.next_fetch, app.next_chain), (1900, 1900))
        with patch.object(bitcoin.threading, 'Thread') as thread, \
             patch.object(bitcoin.time, 'monotonic', return_value=1900):
            app.poll()
            self.assertEqual(thread.call_count, 2)
            app.events.put(('done', None))
            app.events.put(('chain_done', False))
            app.poll()
            self.assertEqual((app.failures, app.chain_failures), (0, 0))
            self.assertEqual((app.next_fetch, app.next_chain), (2020, 2020))

    def test_optional_failures_back_off_without_delaying_healthy_stats(self):
        app = self.make_app()
        with patch.object(bitcoin.time, 'monotonic', return_value=100):
            app.events.put(('chart_error', 'Invalid CoinGecko data'))
            app.events.put(('size_error', 'Invalid Blockchain.com data'))
            app.events.put(('done', None))
            app.events.put(('chain_done', False))
            app.poll()
            self.assertEqual((app.next_fetch, app.next_chain), (220, 220))
            self.assertEqual((app.next_chart, app.next_size), (340, 340))
        with patch.object(bitcoin.threading, 'Thread') as thread, \
             patch.object(bitcoin.time, 'monotonic', return_value=220):
            app.poll()
            self.assertEqual(thread.call_count, 2)
            self.assertTrue(all(call.kwargs['args'] == (False,) for call in thread.call_args_list))

    def test_slow_worker_keeps_navigation_responsive_and_shutdown_is_safe(self):
        app = self.make_app()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def slow_fetch(*args):
            started.set()
            if not release.wait(2):
                raise TimeoutError()
            return {'bitcoin': {'cad': 100, 'last_updated_at': time.time()}}
        original = app.worker
        def worker(*args):
            try:
                original(*args)
            finally:
                finished.set()
        app.data['chart_fetched'] = time.time()
        with patch.object(bitcoin, 'fetch', side_effect=slow_fetch), \
             patch.object(app, 'worker', side_effect=worker):
            app.refresh(True)
            self.assertTrue(started.wait(1))
            app.toggle_settings()
            app.root.update()
            self.assertTrue(app.settings_panel.winfo_ismapped())
            app.escape()
            self.assertTrue(app.busy)
            app.close()
            app.close()
            app.poll()
            release.set()
            self.assertTrue(finished.wait(1))
        self.assertTrue(app.closed)

    def test_optional_broken_icon_does_not_prevent_startup(self):
        with patch.object(bitcoin.Path, 'is_file', return_value=True), \
             patch.object(bitcoin.Path, 'stat') as info, \
             patch.object(bitcoin.tk, 'PhotoImage', side_effect=tk.TclError('bad icon')):
            info.return_value.st_size = 10
            app = self.make_app()
            self.assertTrue(app.root.winfo_exists())

    def test_highlight_expiry_settings_and_toolbar(self):
        root = tk.Tk()
        try:
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(bitcoin, 'SETTINGS', Path(directory) / 'settings.json'), \
                 patch.object(bitcoin.App, 'refresh_all'), \
                 patch.object(bitcoin.App, 'refresh_chain'):
                app = bitcoin.App(root)
                root.update()
                app.data = {'height': 100, 'chain_updated': time.time()}
                app.next_fetch = float('inf')
                app.events.put(('chain', {'height': 101, 'chain_updated': time.time()}))
                with patch.object(bitcoin.time, 'monotonic', return_value=100):
                    app.poll()
                    self.assertEqual(len(app.canvas.find_withtag('block-highlight')), 1)
                with patch.object(bitcoin.time, 'monotonic', return_value=110):
                    app.draw()
                    self.assertFalse(app.canvas.find_withtag('block-highlight'))
                labels = [app.canvas.itemcget(i, 'text') for i in app.canvas.find_all()
                          if app.canvas.type(i) == 'text']
                self.assertIn('app version ' + bitcoin.VERSION, labels)
                app.settings_button.invoke()
                root.update()
                panel = app.settings_panel
                for widget in panel.winfo_children():
                    self.assertGreaterEqual(widget.winfo_y(), 0)
                    self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), panel.winfo_height())
                    self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), panel.winfo_width())
                buttons = [w for w in root.winfo_children() if isinstance(w, tk.Button)]
                for button in buttons:
                    self.assertEqual(button.winfo_height(), 36)
                    self.assertGreaterEqual(button.winfo_x(), 0)
                    self.assertLessEqual(button.winfo_x() + button.winfo_width(), 480)
                    for item in app.canvas.find_all():
                        if app.canvas.type(item) != 'text':
                            continue
                        x1, y1, x2, y2 = app.canvas.bbox(item)
                        overlap = (min(x2, button.winfo_x() + button.winfo_width()) > max(x1, button.winfo_x())
                                   and min(y2, button.winfo_y() + button.winfo_height()) > max(y1, button.winfo_y()))
                        self.assertFalse(overlap, app.canvas.itemcget(item, 'text'))
                app.highlight_until = time.monotonic() + 10
                app.highlight_checkbox.invoke()
                self.assertFalse(app.highlight_enabled)
                self.assertEqual(app.highlight_until, 0)
                self.assertFalse(app.load_settings())
                self.assertFalse(app.canvas.find_withtag('block-highlight'))
                app.escape()
                self.assertIsNone(app.settings_panel)
                self.assertTrue(root.winfo_exists())
                app.toggle_settings()
                self.assertFalse(app.highlight_option.get())
                with patch.object(app, 'save_settings', return_value=False):
                    app.highlight_checkbox.invoke()
                self.assertIn('could not save', app.settings_status.cget('text'))
                app.toggle_settings()
        finally:
            root.destroy()

if __name__ == '__main__':unittest.main()
