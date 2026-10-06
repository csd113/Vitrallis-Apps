"""Fixture-friendly process, disk and throughput sampling for System Monitor."""
from dataclasses import dataclass
import os
import math
from pathlib import Path
import platform
import shutil
import time

from diagnostics import SystemCollector, parse_proc_stat, _read_text
from storage import Paths

APP_ID = 'io.vitrallis.debug'


@dataclass(frozen=True)
class Process:
    pid: int
    name: str
    ticks: int
    start: int
    rss: int
    cpu: float | None = None
    memory: float | None = None


def parse_process(pid, text, page_size=4096):
    if not text or len(text) > 8192:
        return None
    left, right = text.find('('), text.rfind(')')
    if left < 0 or right <= left:
        return None
    fields = text[right+1:].split()
    try:
        if int(text[:left].strip()) != pid or len(fields) < 22:
            return None
        ticks, start, rss = int(fields[11])+int(fields[12]), int(fields[19]), int(fields[21])*page_size
        if min(ticks,start,rss) < 0:
            return None
    except (ValueError,IndexError):
        return None
    name = ''.join(c for c in text[left+1:right] if c.isprintable())[:80] or '?'
    return Process(pid,name,ticks,start,rss)


class ProcessSampler:
    def __init__(self, proc=Path('/proc'), read=_read_text, page_size=None):
        self.proc,self.read,self.previous,self.total=proc,read,{},None
        self.page_size=page_size or os.sysconf('SC_PAGE_SIZE')

    def collect(self,total_memory=None):
        cpu,cores = parse_proc_stat(self.read(self.proc/'stat'))
        total = cpu.total if cpu else None
        delta = total-self.total if total is not None and self.total is not None else 0
        current, result = {}, []
        try:
            with os.scandir(self.proc) as entries:
                for count,entry in enumerate(entries):
                    if count >= 32768:break
                    if not entry.name.isdigit() or entry.is_symlink():continue
                    item=parse_process(int(entry.name),self.read(Path(entry.path)/'stat'),self.page_size)
                    if item is None:continue
                    previous=self.previous.get(item.pid)
                    usage=None
                    if previous and previous.start==item.start and delta>0 and item.ticks>=previous.ticks:
                        usage=100*(item.ticks-previous.ticks)/delta*max(1,len(cores))
                    memory=100*item.rss/total_memory if total_memory and total_memory>0 else None
                    result.append(Process(item.pid,item.name,item.ticks,item.start,item.rss,usage,memory))
                    current[item.pid]=item
        except OSError:
            result=[]
        self.previous,self.total=current,total
        return result


def sorted_processes(items,key='cpu'):
    if key=='name':return sorted(items,key=lambda p:(p.name.casefold(),p.pid))
    return sorted(items,key=lambda p:(-(getattr(p,key) or 0),p.pid))


@dataclass(frozen=True)
class Disk:
    label: str
    total: int
    used: int
    free: int

    @property
    def percent(self):return 100*self.used/self.total if self.total else 0


def disk_sample(path,label,usage=shutil.disk_usage):
    try:
        path=Path(path)
        while not path.exists() and path!=path.parent:path=path.parent
        sample=usage(path)
        if sample.total<=0 or min(sample.used,sample.free)<0:return None
        return Disk(label,sample.total,sample.used,sample.free)
    except (OSError,ValueError):return None


class NetworkRates:
    def __init__(self):self.previous={};self.time=None

    def update(self,interfaces,now):
        elapsed=now-self.time if self.time is not None else 0
        rates,current={},{}
        for item in interfaces:
            if item.rx_bytes is None or item.tx_bytes is None:continue
            value=(item.rx_bytes,item.tx_bytes)
            previous=self.previous.get(item.name)
            if previous and elapsed>0 and all(a>=b for a,b in zip(value,previous)):
                rates[item.name]=tuple((a-b)/elapsed for a,b in zip(value,previous))
            current[item.name]=value
        self.previous,self.time=current,now
        return rates


def parse_wireless(text):
    readings = {}
    for line in (text or '').splitlines():
        name, separator, values = line.partition(':')
        fields = values.split()
        if not separator or len(fields) < 4:
            continue
        try:
            quality, signal_dbm = float(fields[1].strip('.')), float(fields[2].strip('.'))
        except ValueError:
            continue
        if math.isfinite(quality) and math.isfinite(signal_dbm) and 0 <= quality <= 100 and -150 <= signal_dbm <= 0:
            readings[name.strip()[:32]] = (quality, signal_dbm)
    return readings


class MonitorCollector:
    def __init__(self,base=None,proc=Path('/proc'),read=_read_text,clock=time.monotonic,paths=None):
        self.base,self.proc,self.read,self.clock=base or SystemCollector(),proc,read,clock
        self.processes=ProcessSampler(proc,read)
        self.rates=NetworkRates()
        self.paths=paths or Paths(APP_ID)
        self.os_name='Unavailable'
        text=read(Path('/etc/os-release'))
        if text:
            for line in text.splitlines():
                if line.startswith('PRETTY_NAME='):
                    self.os_name=line.split('=',1)[1].strip('"')[:120]
                    break

    def collect(self):
        sample=self.base.collect()
        sample.processes=self.processes.collect(sample.memory.total_kib*1024 if sample.memory else None)
        sample.disks=[disk_sample('/', 'Root'),disk_sample(self.paths.documents,'Documents')]
        sample.network_rates=self.rates.update(sample.network.interfaces if sample.network else (),self.clock())
        sample.wireless=parse_wireless(self.read(self.proc/'net/wireless'))
        sample.os_name=self.os_name
        sample.runtime=f'Python {platform.python_version()} · Tk controls'
        return sample

    def close(self):self.base.close()
