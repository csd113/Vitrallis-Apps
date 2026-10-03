import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor
import tor_transport as tor

ADDRESS = '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'


class MonitorTests(unittest.TestCase):
    def test_address_checksums_and_network(self):
        for value in (ADDRESS, 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4',
                      'bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3',
                      'bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0'):
            self.assertEqual(monitor.address(value), value)
        for value in ('', ADDRESS[:-1]+'b', 'tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx',
                      'bc1Qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4', '../address', 'x'*100,
                      'bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqh2y7hd',
                      'bc1pw5dgrnzv',
                      'bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v07qwwzcrf'):
            with self.subTest(value=value), self.assertRaises(ValueError): monitor.address(value)

    def test_balance_integer_precision_and_pending_spend(self):
        data = {'chain_stats': {'funded_txo_sum': 123456789, 'spent_txo_sum': 1},
                'mempool_stats': {'funded_txo_sum': 0, 'spent_txo_sum': 100}}
        self.assertEqual(monitor.balances(data), {'confirmed': 123456788, 'unconfirmed': -100})
        for invalid in (True, -1, 1.5, monitor.MAX_MONEY+2):
            data['chain_stats']['funded_txo_sum'] = invalid
            with self.assertRaises(ValueError): monitor.balances(data)

    def test_lifetime_totals_can_exceed_supply(self):
        data = dict(chain_stats=dict(funded_txo_sum=monitor.MAX_MONEY*2,
                                     spent_txo_sum=monitor.MAX_MONEY+5),
                    mempool_stats=dict(funded_txo_sum=0, spent_txo_sum=0))
        self.assertEqual(monitor.balances(data)['confirmed'], monitor.MAX_MONEY-5)

    def test_transaction_net_and_status(self):
        row = {'txid': 'a'*64, 'status': {'confirmed': True},
               'vin': [{'prevout': {'scriptpubkey_address': ADDRESS, 'value': 100}}],
               'vout': [{'scriptpubkey_address': ADDRESS, 'value': 40}]}
        self.assertEqual(monitor.transactions([row], ADDRESS)[0]['net'], -60)
        for field, bad in [('vin', [False]), ('vout', ['bad']), ('status', []), ('vin', [{'prevout': 5}])]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                monitor.transactions([dict(row, **{field: bad})], ADDRESS)
        row['status']['confirmed'] = 'yes'
        with self.assertRaises(ValueError): monitor.transactions([row], ADDRESS)

    def test_atomic_watch_persistence_and_hazards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'private/watch.json'
            rows = [{'label': 'Genesis', 'address': ADDRESS}]
            self.assertEqual(monitor.load_watch(path), [])
            monitor.save_watch(rows, path)
            self.assertEqual(monitor.load_watch(path), rows)
            original = path.read_bytes()
            with self.assertRaises(ValueError): monitor.save_watch(rows*2, path)
            self.assertEqual(path.read_bytes(), original)
            link = path.parent / 'link.json'; link.symlink_to(path)
            with self.assertRaises(OSError): monitor.load_watch(link)
            path.write_text('{broken')
            with self.assertRaises(ValueError): monitor.load_watch(path)

    def test_tor_contract_fail_closed(self):
        with patch.dict('os.environ', {}, clear=True): self.assertIsNone(tor.proxy_config())
        good = {'VITRALLIS_TOR_API': '1', 'VITRALLIS_TOR_AVAILABLE': '1',
                'VITRALLIS_TOR_SOCKS_HOST': '127.0.0.1', 'VITRALLIS_TOR_SOCKS_PORT': '9150'}
        with patch.dict('os.environ', good, clear=True): self.assertEqual(tor.proxy_config(), ('127.0.0.1', 9150))
        for key in good:
            with patch.dict('os.environ', dict(good, **{key: 'invalid'}), clear=True):
                with self.assertRaises(OSError): tor.proxy_config()

    def test_socks_uses_remote_domain_and_closes_on_error(self):
        from unittest.mock import Mock
        sock = Mock()
        sock.recv.side_effect = [b'\x05\x00', b'\x05\x00\x00\x01', b'\0'*6]
        with patch.object(tor, 'proxy_config', return_value=('127.0.0.1', 9150)), \
             patch.object(tor.socket, 'create_connection', return_value=sock) as connect:
            self.assertIs(tor.tunnel('mempool.space', 443, 18), sock)
        connect.assert_called_once_with(('127.0.0.1', 9150), timeout=18)
        self.assertIn(b'\x03\x0dmempool.space', sock.sendall.call_args[0][0])
        sock.recv.side_effect = [b'\x05\xff']
        with patch.object(tor, 'proxy_config', return_value=('127.0.0.1', 9150)), \
             patch.object(tor.socket, 'create_connection', return_value=sock):
            with self.assertRaises(OSError): tor.tunnel('mempool.space', 443, 18)
        sock.close.assert_called_once()
