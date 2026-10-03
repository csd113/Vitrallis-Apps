"""Bounded /proc sampling for a manually launched, managed device app."""

import argparse
import json
import re
import subprocess
from pathlib import Path

CODE = r'''
import os, json, pathlib, time
app_id = APP_ID
source_path = SOURCE_PATH
seconds = SECONDS
hz = os.sysconf('SC_CLK_TCK')
page = os.sysconf('SC_PAGE_SIZE')
def snapshot():
    rows = {}
    for p in pathlib.Path('/proc').iterdir():
        if not p.name.isdecimal(): continue
        try:
            fields = (p/'stat').read_text().rsplit(')',1)[1].split()
            command = (p/'cmdline').read_bytes().split(b'\0')
            root = any(part.startswith(source_path.encode()+b'/') for part in command) if source_path else any(('/Apps/'+app_id+'/').encode() in part for part in command)
            rows[int(p.name)] = {'pid':int(p.name),'ppid':int(fields[1]),
                'start':int(fields[19]),'ticks':int(fields[11])+int(fields[12]),
                'rss_kib':int(fields[21])*page//1024,'state':fields[0], 'root':root,
                'name':(p/'comm').read_text().strip()}
        except (OSError,ValueError,IndexError): pass
    ids = {pid for pid,row in rows.items() if row['root']}
    while True:
        more = {pid for pid,row in rows.items() if row['ppid'] in ids}
        if more <= ids: break
        ids |= more
    return {pid:rows[pid] for pid in ids}
observer_started = time.process_time()
previous = snapshot(); then=time.monotonic(); samples=[]; deadline=then+seconds
while time.monotonic() < deadline:
    time.sleep(min(1, max(0, deadline-time.monotonic())))
    current=snapshot(); now=time.monotonic()
    cpu=sum(max(0,row['ticks']-previous[pid]['ticks'])
            for pid,row in current.items() if pid in previous and row['start']==previous[pid]['start'])/hz/(now-then)*100
    samples.append({'elapsed':now-then,'cpu_percent_one_core':cpu,
                    'rss_kib':sum(r['rss_kib'] for r in current.values()),'processes':list(current.values())})
    previous=current;then=now
print(json.dumps({'app_id':app_id,'clock_ticks':hz,'samples':samples,
                  'observer_cpu_seconds':time.process_time()-observer_started},indent=2))
'''

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_id")
    parser.add_argument("name")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--source-snapshot", help="Explicit private source comparison, not a managed app")
    args = parser.parse_args()
    if not re.fullmatch(r"io\.vitrallis\.[a-z]+", args.app_id):
        parser.error("Unknown app namespace")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,90}", args.name) or not 1 <= args.seconds <= 300:
        parser.error("Invalid evidence name or sampling interval")
    source_path = None
    if args.source_snapshot:
        match = re.fullmatch(r"(music|vitrallis-debug|firefly-field|vitrallis-media-carousel)-\d+\.\d+\.\d+(?:-[0-9a-f]{12})?", args.source_snapshot)
        identities = {"music": "io.vitrallis.music", "vitrallis-debug": "io.vitrallis.debug",
                      "firefly-field": "io.vitrallis.fireflyfield", "vitrallis-media-carousel": "io.vitrallis.mediacarousel"}
        if not match or identities[match.group(1)] != args.app_id:
            parser.error("Source snapshot identity mismatch")
        source_path = "/home/chip/vitrallis-apps-hardware-2026-10-03/source/" + args.source_snapshot
    code = CODE.replace("APP_ID", repr(args.app_id)).replace("SECONDS", str(args.seconds)).replace("SOURCE_PATH", repr(source_path))
    result = subprocess.run(["ssh", "-oBatchMode=yes", "-oConnectTimeout=10",
                             "chip@192.168.81.1", "python3 -"],
                            input=code, text=True, capture_output=True,
                            check=True, timeout=args.seconds + 30)
    data = json.loads(result.stdout)
    folder = Path(__file__).resolve().parents[2] / "target/apps-hardware-2026-10-03"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (args.name + ".json")).write_text(result.stdout)
    samples = data["samples"]
    elapsed = sum(s["elapsed"] for s in samples)
    print(json.dumps({"app": args.app_id, "source_snapshot": args.source_snapshot, "requested_seconds": args.seconds,
                      "actual_seconds": elapsed, "sample_count": len(samples),
                      "observer_cpu_percent_one_core": data["observer_cpu_seconds"] / elapsed * 100,
                      "mean_cpu_percent_one_core": sum(s["cpu_percent_one_core"] * s["elapsed"] for s in samples) / elapsed,
                      "max_rss_kib": max(s["rss_kib"] for s in samples),
                      "processes_at_end": samples[-1]["processes"]}, indent=2))
