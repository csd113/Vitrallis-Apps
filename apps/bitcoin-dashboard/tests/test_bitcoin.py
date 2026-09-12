import json
import io
import math
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler
from http.client import IncompleteRead, BadStatusLine
from contextlib import redirect_stderr
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as bitcoin


class DataTests(unittest.TestCase):
    def make_app(self):
        app = object.__new__(bitcoin.App)
        app.events = bitcoin.queue.Queue()
        app.data = {'price': 12}
        return app

    def stats(self):
        return {'n_blocks_total': 966272, 'totalbc': 2008210000000000,
                'timestamp': time.time() * 1000}

    def size(self):
        return {'status': 'ok', 'unit': 'MB', 'values': [
            {'x': time.time()-86400, 'y': 767103.638627}]}

    def test_quote_validation(self):
        good = {'bitcoin': {'cad': 100000, 'cad_24h_change': -1.5, 'last_updated_at': time.time()}}
        self.assertEqual(bitcoin.quote(good)['price'], 100000)
        for bad in [None, True, -1, 0, float('nan'), float('inf'), '100000']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bitcoin.quote({'bitcoin': dict(good['bitcoin'], cad=bad)})

    def test_history_validation(self):
        t = time.time() * 1000 - 600000
        self.assertEqual(len(bitcoin.history({'prices': [[t, 5], [t + 1000, 6]]})), 2)
        for rows in [[], [[t, 5]], [[t, 5], [t, 6]], [[t, 5], [t-1, 6]],
                     [[t, 5], [t+1, float('nan')]], [[t, 5], [t+1, -2]]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                bitcoin.history({'prices': rows})

    def test_errors(self):
        self.assertEqual(bitcoin.error_label(HTTPError('', 429, '', {}, None)), 'Rate limited')
        self.assertEqual(bitcoin.error_label(URLError('offline')), 'Offline / connection error')
        self.assertEqual(bitcoin.error_label(URLError(bitcoin.ssl.SSLCertVerificationError())),
                         'TLS error: check clock / certificates')

    def test_startup_errors_explain_missing_tk_and_display(self):
        output = io.StringIO()
        with patch.object(bitcoin, 'tk', None), redirect_stderr(output):
            self.assertEqual(bitcoin.main(), 1)
        self.assertIn('install python3-tk', output.getvalue())
        output = io.StringIO()
        with patch.object(bitcoin.tk, 'Tk', side_effect=bitcoin.tk.TclError('no display')), \
             redirect_stderr(output):
            self.assertEqual(bitcoin.main(), 1)
        self.assertIn('graphical desktop', output.getvalue())

    def test_offline_worker_finishes_without_losing_quote(self):
        app = self.make_app()
        with patch.object(bitcoin, 'fetch', side_effect=URLError('offline')):
            app.worker(True)
        self.assertEqual(app.events.get_nowait(), ('done', 'Offline / connection error'))
        self.assertEqual(app.data['price'], 12)

    def test_chart_failure_preserves_successful_price(self):
        app = self.make_app()
        row = {'bitcoin': {'cad': 100000, 'last_updated_at': time.time()}}
        with patch.object(bitcoin, 'fetch', side_effect=[row, ValueError('bad chart')]):
            app.worker(True)
        self.assertEqual(app.events.get_nowait()[0], 'quote')
        self.assertEqual(app.events.get_nowait()[0], 'chart_error')
        self.assertEqual(app.events.get_nowait(), ('done', None))

    def test_corrupt_cache_does_not_crash(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'data.json'
            cache.write_text('{invalid')
            with patch.object(bitcoin, 'CACHE', cache):
                app.load_cache()
        self.assertEqual(app.data, {'price': 12})

    def test_genesis_count_to_height_and_satoshi_to_btc(self):
        result = bitcoin.chain_stats(self.stats())
        self.assertEqual(result['height'], 966271)
        self.assertEqual(result['supply_sats'], 2008210000000000)
        genesis = dict(self.stats(), n_blocks_total=1, totalbc=5000000000)
        self.assertEqual(bitcoin.chain_stats(genesis)['height'], 0)
        fractional = dict(self.stats(), totalbc=2008210312500000)
        self.assertEqual(bitcoin.chain_stats(fractional)['supply_sats'], 2008210312500000)

    def test_bad_network_values_rejected(self):
        for field, values in {
            'n_blocks_total': [True, 0, -1, 1.2, '999', float('inf'), 100000001],
            'totalbc': [True, 0, -1, float('nan'), 2100000000000001],
            'timestamp': [0, float('nan'), (time.time()+600)*1000]
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    bitcoin.chain_stats(dict(self.stats(), **{field: value}))

    def test_size_uses_latest_sample_and_decimal_gb(self):
        data = self.size()
        data['values'].append({'x': time.time()-172800, 'y': 766000})
        result = bitcoin.blockchain_size(data)
        self.assertAlmostEqual(result['chain_gb'], 767.103638627)
        self.assertEqual(result['size_updated'], data['values'][0]['x'])

    def test_invalid_sizes_rejected(self):
        for data in [dict(self.size(), unit='GB'), dict(self.size(), status='error'),
                     dict(self.size(), values=[]), dict(self.size(), values=[{'x': time.time(), 'y': -1}]),
                     dict(self.size(), values=[{'x': time.time()+1000, 'y': 100}])]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                bitcoin.blockchain_size(data)

    def test_size_failure_retains_new_height_and_supply(self):
        app = self.make_app()
        with patch.object(bitcoin, 'fetch', side_effect=[self.stats(), URLError('offline')]):
            app.chain_worker(True)
        self.assertEqual(app.events.get_nowait()[0], 'chain')
        self.assertEqual(app.events.get_nowait()[0], 'size_error')
        # Optional size outages must not slow otherwise healthy network stats.
        self.assertEqual(app.events.get_nowait(), ('chain_done', False))

    def test_stats_failure_does_not_block_size(self):
        app = self.make_app()
        with patch.object(bitcoin, 'fetch', side_effect=[URLError('offline'), self.size()]):
            app.chain_worker(True)
        self.assertEqual(app.events.get_nowait()[0], 'chain_error')
        self.assertEqual(app.events.get_nowait()[0], 'size')
        self.assertEqual(app.events.get_nowait(), ('chain_done', True))

    def test_cached_size_avoids_another_size_request(self):
        app = self.make_app()
        with patch.object(bitcoin, 'fetch', return_value=self.stats()) as fetch:
            app.chain_worker(False)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(app.events.get_nowait()[0], 'chain')
        self.assertEqual(app.events.get_nowait(), ('chain_done', False))

    def test_cache_roundtrip_and_independent_validation(self):
        app = self.make_app()
        app.data.update(bitcoin.chain_stats(self.stats()))
        app.data.update(bitcoin.blockchain_size(self.size()))
        app.data.update(size_fetched=time.time(), updated=time.time(), points='bad chart')
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'data.json'
            with patch.object(bitcoin, 'CACHE', cache):
                app.save_cache()
                restored = self.make_app()
                restored.load_cache()
            self.assertEqual(restored.data['height'], 966271)
            self.assertEqual(restored.data['supply_sats'], 2008210000000000)
            self.assertAlmostEqual(restored.data['chain_gb'], 767.103638627)
            self.assertNotIn('points', restored.data)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)

    def test_api_key_is_never_sent_to_blockchain(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read1.side_effect = [b'{}', b'', b'{}', b'']
        with patch.dict(bitcoin.os.environ, {'COINGECKO_DEMO_API_KEY': 'test-key'}), \
             patch.object(bitcoin, 'build_opener') as opener:
            open_url = opener.return_value.open
            open_url.return_value = response
            bitcoin.fetch('stats', bitcoin.CHAIN_BASE)
            self.assertFalse(open_url.call_args[0][0].has_header('X-cg-demo-api-key'))
            bitcoin.fetch('simple/price')
            self.assertEqual(open_url.call_args[0][0].get_header('X-cg-demo-api-key'), 'test-key')
            request = open_url.call_args[0][0]
            redirected = HTTPRedirectHandler().redirect_request(
                request, None, 302, 'redirect', {}, 'https://example.com/')
            self.assertFalse(redirected.has_header('X-cg-demo-api-key'))

    def test_redirects_preserve_https_and_provider(self):
        handler = bitcoin.SafeRedirectHandler()
        request = Request(bitcoin.BASE + 'simple/price')
        for target in ('http://api.coingecko.com/path', 'https://example.com/',
                       'https://api.coingecko.com:444/path',
                       'https://user@api.coingecko.com/path'):
            with self.subTest(target=target), self.assertRaises(URLError):
                handler.redirect_request(request, None, 302, '', {}, target)
        result = handler.redirect_request(request, None, 302, '', {}, bitcoin.BASE + 'new')
        self.assertEqual(result.full_url, bitcoin.BASE + 'new')

    def test_invalid_key_is_rejected_before_network_and_not_exposed(self):
        for key in ('secret\nheader', 'secret\t', 'x' * 513, ' secret', 'clé'):
            with self.subTest(key_length=len(key)), \
                 patch.dict(bitcoin.os.environ, {'COINGECKO_DEMO_API_KEY': key}), \
                 patch.object(bitcoin, 'build_opener') as opener:
                with self.assertRaises(bitcoin.ConfigurationError) as caught:
                    bitcoin.fetch('simple/price')
                opener.assert_not_called()
                self.assertNotIn(key, str(caught.exception))
                self.assertEqual(bitcoin.error_label(caught.exception),
                                 'Check COINGECKO_DEMO_API_KEY')

    def test_fetch_limits_response_size_and_timeout(self):
        response = unittest.mock.MagicMock()
        with patch.object(bitcoin, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            response.__enter__.return_value.read1.return_value = b' ' * 1_000_001
            with self.assertRaises(ValueError):
                bitcoin.fetch('simple/price')
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], 18)
            response.__enter__.return_value.read1.assert_called_once_with(65536)

    def test_slow_trickling_body_cannot_hold_worker_forever(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read1.return_value = b' '
        with patch.object(bitcoin, 'build_opener') as opener, \
             patch.object(bitcoin.time, 'monotonic', side_effect=[0, 1, 31]):
            opener.return_value.open.return_value = response
            with self.assertRaises(TimeoutError):
                bitcoin.fetch('simple/price')
        response.__exit__.assert_called_once()

    def test_workers_complete_on_truncated_deep_and_extreme_data(self):
        for error in (IncompleteRead(b'partial'), BadStatusLine('broken'),
                      RecursionError('deep'), OverflowError('huge'), TypeError('shape')):
            with self.subTest(error=type(error).__name__):
                app = self.make_app()
                with patch.object(bitcoin, 'fetch', side_effect=error):
                    app.worker(True)
                self.assertEqual(app.events.get_nowait()[0], 'done')
                self.assertTrue(app.events.empty())
                with patch.object(bitcoin, 'fetch', side_effect=error):
                    app.chain_worker(True)
                self.assertEqual(app.events.get_nowait()[0], 'chain_error')
                self.assertEqual(app.events.get_nowait()[0], 'size_error')
                self.assertEqual(app.events.get_nowait(), ('chain_done', True))
                self.assertEqual(app.data, {'price': 12})

    def test_giant_numbers_and_malformed_quote_shapes_are_rejected(self):
        for value in (10 ** 400, True, float('nan')):
            with self.subTest(value_type=type(value)), self.assertRaises(ValueError):
                bitcoin.number(value)
        for row in (None, [], 'invalid', 12):
            with self.subTest(row=row), self.assertRaises(ValueError):
                bitcoin.quote({'bitcoin': row})

    def test_supply_is_exact_through_cache(self):
        sats = 2008210312500002  # The former BTC float round trip became ...001.8.
        app = self.make_app()
        app.data.update(bitcoin.chain_stats(dict(self.stats(), totalbc=sats)))
        self.assertEqual(app.data['supply_sats'], sats)
        self.assertEqual(bitcoin.format_supply(sats), '20,082,103.125')
        self.assertEqual(bitcoin.format_supply(bitcoin.MAX_SUPPLY), '21,000,000.000')
        self.assertEqual(bitcoin.format_supply(123450000), '1.234')
        self.assertEqual(bitcoin.format_supply(123550000), '1.236')
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'data.json'
            with patch.object(bitcoin, 'CACHE', cache):
                app.save_cache()
                restored = self.make_app()
                restored.load_cache()
                self.assertEqual(restored.data['supply_sats'], sats)

    def test_deep_oversized_and_nonregular_cache_are_ignored(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'data.json'
            with patch.object(bitcoin, 'CACHE', cache):
                for content in ('[' * 2000 + ']' * 2000, ' ' * 1_000_001, '\ufffd'):
                    cache.write_text(content)
                    app.load_cache()
                    self.assertEqual(app.data, {'price': 12})
                cache.unlink()
                os.mkfifo(cache)
                app.load_cache()
                self.assertEqual(app.data, {'price': 12})

                cache.unlink()
                target = Path(directory) / 'target'
                target.write_text('{}')
                cache.symlink_to(target)
                app.load_cache()
                self.assertEqual(app.data, {'price': 12})

    def test_missing_session_cache_does_not_read_another_location(self):
        app = self.make_app()
        with patch.object(bitcoin, 'read_json', side_effect=FileNotFoundError) as read:
            app.load_cache()
        read.assert_called_once_with(bitcoin.CACHE, 1_000_000)
        self.assertEqual(app.data, {'price': 12})

    def test_cache_requires_satoshi_supply_without_discarding_valid_quote(self):
        app = self.make_app()
        raw = {'price': 100000, 'updated': time.time(), 'height': 966271,
               'chain_updated': time.time(), 'supply': 20082100.0}
        with patch.object(bitcoin, 'read_json', return_value=raw):
            app.load_cache()
        self.assertEqual(app.data['price'], 100000)
        self.assertNotIn('supply_sats', app.data)
        self.assertNotIn('height', app.data)

    def test_cache_write_rejects_symlink_directory_and_survives_cleanup_error(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            linked = parent / 'link'
            linked.symlink_to(parent, target_is_directory=True)
            with patch.object(bitcoin, 'CACHE', linked / 'data.json'):
                app.save_cache()
                self.assertFalse((parent / 'data.json').exists())
            cache = parent / 'data.json'
            cache.write_text('previous')
            with patch.object(bitcoin, 'CACHE', cache), \
                 patch.object(bitcoin.os, 'replace', side_effect=OSError('full')), \
                 patch.object(bitcoin.os, 'unlink', side_effect=OSError('denied')):
                app.save_cache()
            self.assertEqual(cache.read_text(), 'previous')

    def test_chart_extremes_stay_finite_and_sampling_preserves_spikes(self):
        for points in ([[1, 1e308], [2, 1.79e308]], [[1, 5e-324], [2, 5e-324]],
                       [[1, 5e-324], [2, 1.79e308]]):
            coords = bitcoin.chart_coordinates(points, 249, 467, 75, 115)
            self.assertTrue(all(math.isfinite(value) for value in coords))
            self.assertTrue(all(249 <= x <= 467 for x in coords[::2]))
            self.assertTrue(all(75 <= y <= 115 for y in coords[1::2]))
        points = [[i + 1, 10] for i in range(5000)]
        points[1234][1] = 1000
        coords = bitcoin.chart_coordinates(points, 249, 467, 75, 115)
        self.assertLessEqual(len(coords), 4 * 220 + 4)
        self.assertLess(min(coords[1::2]), 80)
        self.assertEqual((coords[0], coords[-2]), (249, 467))


class BlockIndicatorTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(bitcoin.App)
        self.app.data = {}
        self.app.highlight_enabled = True
        self.app.highlight_until = 0
        self.now = time.time()

    def update(self, height, age=0):
        with patch.object(bitcoin.time, 'monotonic', return_value=100):
            self.app.update_chain({'height': height, 'chain_updated': self.now - age})

    def test_initial_equal_and_lower_heights_do_not_highlight(self):
        for height in (100, 100, 99):
            self.update(height)
            self.assertEqual(self.app.highlight_until, 0)
            self.assertEqual(self.app.data['height'], height)

    def test_higher_height_highlights_and_repeated_height_does_not_extend(self):
        self.update(100)
        self.update(102)
        self.assertEqual(self.app.highlight_until, 110)
        with patch.object(bitcoin.time, 'monotonic', return_value=103):
            self.app.update_chain({'height': 102, 'chain_updated': self.now})
        self.assertEqual(self.app.highlight_until, 110)

    def test_mainnet_subsidy_boundaries_and_exact_btc(self):
        for height, expected in ((0, 5000000000), (209999, 5000000000),
                                 (210000, 2500000000), (839999, 625000000),
                                 (840000, 312500000), (1049999, 312500000),
                                 (1050000, 156250000), (6720000, 1),
                                 (6930000, 0), (13440000, 0), (99999999, 0)):
            with self.subTest(height=height):
                self.assertEqual(bitcoin.subsidy_at_height(height), expected)
        self.assertEqual(bitcoin.format_btc(1), '0.00000001')
        self.assertEqual(bitcoin.format_btc(2008210312500002), '20,082,103.12500002')

    def test_disabled_delayed_and_out_of_order_updates_do_not_highlight(self):
        self.update(100)
        self.app.highlight_enabled = False
        self.update(101)
        self.assertEqual(self.app.highlight_until, 0)
        self.app.highlight_enabled = True
        self.update(102, age=901)
        self.assertEqual(self.app.highlight_until, 0)
        self.update(103)
        self.app.highlight_until = 0
        self.update(104, age=1)
        self.assertEqual(self.app.highlight_until, 0)

    def test_settings_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'private/settings.json'
            with patch.object(bitcoin, 'SETTINGS', settings):
                self.assertTrue(self.app.load_settings())
                self.app.highlight_enabled = False
                self.assertTrue(self.app.save_settings())
                self.assertFalse(self.app.load_settings())
                self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
                for raw in ('{bad', '[]', '{"highlight_new_blocks": "false"}',
                            '{"highlight_new_blocks": 0}', ' ' * 4097 + '{}'):
                    settings.write_text(raw)
                    self.assertTrue(self.app.load_settings())

    def test_failed_settings_replace_preserves_previous_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.json'
            with patch.object(bitcoin, 'SETTINGS', settings):
                self.app.highlight_enabled = False
                self.assertTrue(self.app.save_settings())
                self.app.highlight_enabled = True
                with patch.object(bitcoin.os, 'replace', side_effect=OSError('disk full')):
                    self.assertFalse(self.app.save_settings())
                self.assertFalse(self.app.load_settings())
                self.assertEqual(list(Path(directory).iterdir()), [settings])

    def test_settings_unsafe_directory_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'public'
            parent.mkdir(mode=0o755)
            with patch.object(bitcoin, 'SETTINGS', parent / 'settings.json'):
                self.assertFalse(self.app.save_settings())
                self.assertFalse((parent / 'settings.json').exists())


if __name__ == '__main__':
    unittest.main()
