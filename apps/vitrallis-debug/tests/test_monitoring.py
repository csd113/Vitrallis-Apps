from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from monitoring import (ProcessSampler, NetworkRates, disk_sample, parse_process, sorted_processes)
from diagnostics import History


def stat(pid=12,ticks=10,start=50,rss=100):
    fields=['S']+['0']*21
    fields[11]=str(ticks);fields[12]='2';fields[19]=str(start);fields[21]=str(rss)
    return f'{pid} (name with ) parens) '+' '.join(fields)


class ParserTests(unittest.TestCase):
    def test_process_stat_names_ticks_start_rss_and_malformed(self):
        p=parse_process(12,stat())
        self.assertEqual((p.name,p.ticks,p.start,p.rss),('name with ) parens',12,50,409600))
        for text in ('',None,'12 x','12 (name) S 2',stat(rss=-1),stat(pid=13)):
            self.assertIsNone(parse_process(12,text))

    def test_cpu_delta_memory_pid_reuse_and_missing_process(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'12').mkdir();(root/'12/stat').write_text(stat())
            (root/'stat').write_text('cpu 10 0 0 90\ncpu0 10 0 0 90\n')
            sampler=ProcessSampler(root,page_size=4096)
            first=sampler.collect(4096000);self.assertIsNone(first[0].cpu);self.assertEqual(first[0].memory,10)
            (root/'stat').write_text('cpu 30 0 0 170\ncpu0 30 0 0 170\n')
            (root/'12/stat').write_text(stat(ticks=30))
            self.assertEqual(sampler.collect(4096000)[0].cpu,20)
            (root/'12/stat').write_text(stat(ticks=1,start=99))
            self.assertIsNone(sampler.collect(4096000)[0].cpu)
            (root/'12/stat').unlink();self.assertEqual(sampler.collect(),[])

    def test_permission_denied_and_invalid_proc(self):
        with tempfile.TemporaryDirectory() as t:
            sampler=ProcessSampler(Path(t),read=lambda _:None)
            self.assertEqual(sampler.collect(),[])
            with patch('monitoring.os.scandir',side_effect=PermissionError):self.assertEqual(sampler.collect(),[])

    def test_disk_calculation_reserved_space_missing_and_denied(self):
        d=disk_sample('/','Root',lambda _:SimpleNamespace(total=100,used=60,free=35))
        self.assertEqual((d.percent,d.free),(60,35))
        self.assertIsNone(disk_sample('/','Root',lambda _:SimpleNamespace(total=0,used=0,free=0)))
        with patch('monitoring.shutil.disk_usage',side_effect=PermissionError):
            self.assertIsNone(disk_sample('/','Root',lambda _:(_ for _ in ()).throw(PermissionError())))

    def test_network_deltas_reset_missing_and_bounded_history(self):
        r=NetworkRates()
        item=lambda rx,tx:SimpleNamespace(name='wlan0',rx_bytes=rx,tx_bytes=tx)
        self.assertEqual(r.update([item(100,50)],10),{})
        self.assertEqual(r.update([item(300,150)],12),{'wlan0':(100,50)})
        self.assertEqual(r.update([item(1,1)],13),{})
        self.assertEqual(r.update([item(None,None)],14),{})
        h=History()
        for i in range(10000):h.add(float(i))
        self.assertEqual(len(h.items()),60)

    def test_process_sorts_are_deterministic(self):
        p=parse_process(12,stat());q=parse_process(13,stat(pid=13))
        self.assertEqual([x.pid for x in sorted_processes([q,p],'cpu')],[12,13])
        self.assertEqual([x.pid for x in sorted_processes([q,p],'memory')],[12,13])
        self.assertEqual([x.pid for x in sorted_processes([q,p],'name')],[12,13])


class WirelessTests(unittest.TestCase):
    def test_wireless_fixture_and_malformed_values(self):
        from monitoring import parse_wireless
        self.assertEqual(parse_wireless('wlan0: 0000 65. -42. -90. 0 0 0 0 0 0'),{'wlan0':(65,-42)})
        for text in ('wlan0: nope','wlan0: 0000 nan -42 0','wlan0: 0000 101 -42 0','wlan0: 0000 50 999 0'):
            self.assertEqual(parse_wireless(text),{})
