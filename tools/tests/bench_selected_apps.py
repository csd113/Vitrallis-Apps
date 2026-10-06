"""Small repeatable host microbenchmarks; never PocketCHIP measurements."""
import sys
sys.dont_write_bytecode=True
import json
from pathlib import Path
import resource
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
slug=sys.argv[1]
sys.path.insert(0,str(ROOT/'apps'/slug))
with tempfile.TemporaryDirectory() as t:
    root=Path(t).resolve()
    if slug=='music':
        from player import scan
        for i in range(1000):(root/f'Track-{i:04}.mp3').write_bytes(b'')
        operation=lambda:scan(root)
        count=10
    elif slug=='sketch':
        from drawing import Drawing
        model=Drawing()
        def operation():
            model.begin(0,0)
            model.stroke(463,193)
            model.end()
        count=200
    else:
        from monitoring import ProcessSampler
        (root/'stat').write_text('cpu 10 0 0 90\ncpu0 10 0 0 90\n')
        for pid in range(100):
            path=root/str(pid);path.mkdir();fields=['S']+['0']*21;fields[11]='10';fields[12]='2';fields[19]='50';fields[21]='100'
            (path/'stat').write_text(f'{pid} (fixture) '+' '.join(fields))
        sampler=ProcessSampler(root,page_size=4096)
        operation=lambda:sampler.collect(512*1024*1024)
        count=100
    cpu=time.process_time();wall=time.monotonic()
    for _ in range(count):operation()
    cpu=time.process_time()-cpu;wall=time.monotonic()-wall
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform!='darwin':rss*=1024
    print(json.dumps({'app':slug,'operations':count,'wall_ms_each':round(wall*1000/count,3),'cpu_ms_each':round(cpu*1000/count,3),'process_peak_mib':round(rss/1024/1024,2),'host':sys.platform}))
