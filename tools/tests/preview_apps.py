"""Disposable 480×272 fixture previews; never uses real user files or audio."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import os
import signal
import tempfile
import tkinter as tk

ROOT=Path(__file__).resolve().parents[2]
slug=sys.argv[1]
with tempfile.TemporaryDirectory(prefix='vitrallis-preview-') as t:
    home=str(Path(t).resolve())
    os.environ.update(HOME=home,XDG_CONFIG_HOME=home+'/config',XDG_CACHE_HOME=home+'/cache',XDG_DATA_HOME=home+'/data')
    os.environ.pop('VITRALLIS_DOCUMENTS_DIR',None)
    os.environ.pop('VITRALLIS_APP_ID',None)
    sys.path.insert(0,str(ROOT/'apps'/slug))
    root=tk.Tk();root.geometry('480x272')
    if slug=='vitrallis-debug':
        from demo import DemoCollector
        from monitoring import Disk, Process
        from monitor_ui import Monitor
        app=Monitor(root,tk,DemoCollector(),demo=True)
        root.title('System Monitor · Demo')
        sample=DemoCollector().collect()
        sample.disks=[Disk('Root',4*1024**3,2*1024**3,2*1024**3)]
        sample.processes=[Process(i,name,10,10,4096,usage,mem) for i,name,usage,mem in [(421,'Music',4.1,1.3),(122,'vitrallis-shell',2.2,3.4),(318,'System Monitor',1.8,1.2),(115,'Xorg',0.8,2.1)]]
        sample.network_rates={'wlan-demo':(8192,1024)}
        sample.architecture='armv7l';sample.uptime_seconds=8300
        app.snapshot=sample
        if len(sys.argv)>2:app.switch(int(sys.argv[2]))
    else:
        from main import App
        app=App(root)
        if slug=='calculator':
            for key in '(128+64)/3=':app.press(key)
        elif slug=='sketch':
            for color,points in [(3,[(20,150),(140,40),(260,150)]),(5,[(200,180),(300,110),(450,180)]),(4,[(20,185),(140,145),(270,185)])]:
                app.model.color=color;app.model.size=3
                app.model.begin(*points[0])
                for point in points[1:]:app.model.stroke(*point)
                app.model.end()
            app.render()
        elif slug=='music':
            from player import Track
            app.track=Track(Path(home)/'Quiet Morning.flac','Quiet Morning','Pocket Sessions','Small Screen Sounds',214)
            root.after(800, app.show_track)
    signal.signal(signal.SIGTERM,lambda *_:app.close())
    signal.signal(signal.SIGINT,lambda *_:app.close())
    root.mainloop()
