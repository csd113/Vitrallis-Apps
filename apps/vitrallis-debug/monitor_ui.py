"""Small overview/process/network surfaces; original diagnostics remain optional."""
from pathlib import Path
import time

from diagnostics import History
from monitoring import APP_ID, MonitorCollector, sorted_processes
from storage import Paths, atomic_write
from ui import Dashboard, BACKGROUND, CARD, TEXT, MUTED, ACCENT, WARN

SECTIONS=('Overview','Processes','Network','Diagnostics')


def percent(value):return '—' if value is None else f'{value:.1f}%'
def mib(value):return f'{value/1024/1024:.0f} MiB'


class Monitor(Dashboard):
    def __init__(self,root,tk,collector=None,**kwargs):
        self.section,self.section_focus,self.row,self.sort='Overview',0,0,'cpu'
        self.rx_history,self.tx_history=History(),History()
        self.report_status=''
        self.section_press=None
        self.paths=Paths(APP_ID)
        super().__init__(root,tk,collector or MonitorCollector(paths=self.paths),**kwargs)

    def _drain_results(self):
        updated=super()._drain_results()
        if updated:
            rates=getattr(self.snapshot,'network_rates',{})
            item=self.snapshot.network.primary if self.snapshot.network else None
            rx,tx=rates.get(item.name,(None,None)) if item else (None,None)
            self.rx_history.add(rx);self.tx_history.add(tx)
        return updated

    def switch(self,index):
        if self.model.pulse.cancel():self._clear_pulse()
        self.model.close()
        self.section,self.section_focus,self.row=SECTIONS[index],index,0
        self.detail_canvas.place_forget()
        self._render()

    def _key(self,event):
        if event.char in ('1','2','3','4'):
            self.switch(int(event.char)-1);return 'break'
        if self.section=='Diagnostics':
            if event.char.lower()=='s':self.save_report();return 'break'
            if event.keysym=='Escape' and self.model.expanded is None and not self.model.pulse.active:
                self.switch(0);return 'break'
            return super()._key(event)
        key=event.keysym
        if key=='Escape':
            if self.section!='Overview':self.switch(0)
            else:self.close()
        elif key in ('Tab','ISO_Left_Tab','Left','Right'):
            self.section_focus=(self.section_focus+(-1 if key in ('Left','ISO_Left_Tab') or event.state&1 else 1))%5
            self._render()
        elif key in ('Return','space','KP_Enter'):
            self.close() if self.section_focus==4 else self.switch(self.section_focus)
        elif key in ('Up','Down','Prior','Next') and self.section=='Processes':
            self.row=max(0,self.row+(-1 if key=='Up' else -6 if key=='Prior' else 6 if key=='Next' else 1));self._render()
        elif event.char.lower()=='s' and self.section=='Processes':
            self.sort={'cpu':'memory','memory':'name','name':'cpu'}[self.sort];self.row=0;self._render()
        else:return None
        return 'break'

    def _press(self,event):
        if self.section=='Diagnostics':
            target=self._monitor_target(event.x,event.y)
            if self.model.expanded is None and not self.model.pulse.active and target and target.isdigit():
                self.section_press=target
                return
            return super()._press(event)
        self.model.press(self._monitor_target(event.x,event.y) or '')
        self.canvas.focus_set()

    def _release(self,event):
        if self.section=='Diagnostics':
            if self.section_press is not None:
                pressed,self.section_press=self.section_press,None
                target=self._monitor_target(event.x,event.y)
                if target==pressed:self.switch(int(target))
                return
            return super()._release(event)
        target=self._monitor_target(event.x,event.y)
        if target and self.model.release(target):
            if target=='exit':self.close()
            elif target=='sort':self.sort={'cpu':'memory','memory':'name','name':'cpu'}[self.sort];self._render()
            elif target=='up':self.row=max(0,self.row-6);self._render()
            elif target=='down':self.row+=6;self._render()
            else:self.switch(int(target))

    def _monitor_target(self,x,y):
        if 4<=y<=34 and 8<=x<472:return str(min(3,int((x-8)//116)))
        if y>=238:
            if x>390:return 'exit'
            if self.section=='Processes':return 'sort' if x<230 else 'up' if x<308 else 'down' if x<390 else 'exit'
        return None

    def _render(self):
        if self.closed:return
        if self.section=='Diagnostics':
            super()._render()
            height=self.canvas.winfo_height()
            self.canvas.create_rectangle(128,height-40,self.canvas.winfo_width()-120,height-8,
                                         fill=BACKGROUND,outline='',tags='dashboard')
            message=self.report_status or ('Esc: back · S: report' if self.model.expanded is not None else 'S: save report')
            self._text(132,height-30,message,self.canvas.winfo_width()-260,size=11,color=MUTED)
            if self.model.expanded is not None or self.model.pulse.active:
                return
            # Header is a shallow route back to the user-facing surfaces.
            self.canvas.create_rectangle(0,0,self.canvas.winfo_width(),33,fill=BACKGROUND,outline='',tags='dashboard')
            self.tabs()
            return
        self.detail_canvas.place_forget();self.pulse_layer.place_forget()
        self.canvas.delete('dashboard')
        self.tabs()
        if self.section=='Overview':self.overview()
        elif self.section=='Processes':self.process_view()
        else:self.network_view()
        self._button((394,238,472,268),'Exit',self.section_focus==4)
        if self.section!='Processes':self._text(10,249,('DEMO · ' if self.demo else '')+'1–4 sections · Tab / Enter · Esc back',370,size=11,color=MUTED)

    def tabs(self):
        for i,name in enumerate(SECTIONS):
            x=8+i*116
            self._button((x,4,x+110,32),f'{i+1} {name}',self.section_focus==i)

    def overview(self):
        sample=self.snapshot
        cards=[]
        if not sample:
            self._text(16,70,'Collecting system information…',445,size=16);return
        memory=sample.memory
        cards.append(('CPU',percent(sample.cpu_percent),f'Load {sample.load_averages[0]:.2f}' if sample.load_averages else 'Load unavailable',self.cpu_history.items()))
        cards.append(('RAM',percent(memory.percent if memory else None),f'{memory.used_kib/1024:.0f}/{memory.total_kib/1024:.0f} MiB' if memory else 'Unavailable',self.memory_history.items()))
        cards.append(('GPU',percent(sample.gpu.percent if sample.gpu else None),f'{sample.gpu_frequency_hz/1e6:.0f} MHz' if sample.gpu_frequency_hz else 'Frequency unavailable' if sample.gpu else 'Counter unavailable',self.gpu_history.items()))
        sensor=next((s for s in sample.sensors if s.selected),None)
        cards.append(('SoC',f'{sensor.celsius:.1f} °C' if sensor else '—','Temperature' if sensor else 'Sensor unavailable',self.temp_history.items()))
        for i,(label,value,detail,history) in enumerate(cards):
            x,y=8+(i%2)*234,40+(i//2)*66
            self.canvas.create_rectangle(x,y,x+226,y+60,fill=CARD,outline='',tags='dashboard')
            self._text(x+8,y+5,label,52,size=11,color=ACCENT)
            self._text(x+61,y+4,value,95,size=18,bold=True)
            self._text(x+8,y+38,detail,210,size=11,color=MUTED)
            self._sparkline(x+154,y+8,x+216,y+30,history,ACCENT,percent=label!='SoC')
        disks=getattr(sample,'disks',[])
        root=next((d for d in disks if d and d.label=='Root'),None)
        self._text(10,175,f'Root {root.percent:.0f}% · {mib(root.free)} free' if root else 'Root storage unavailable',462,size=12)
        frequency=f'{sample.frequency.mhz:.0f} MHz' if sample.frequency else 'frequency —'
        swap=f'{((memory.swap_total_kib or 0)-(memory.swap_free_kib or 0))/1024:.0f} MiB swap' if memory else 'swap —'
        available=f'{memory.available_kib/1024:.0f} MiB available' if memory else 'RAM —'
        self._text(10,197,f'{frequency} · {available} · {swap}',462,size=11,color=MUTED)
        uptime=f'{sample.uptime_seconds/3600:.1f}h uptime' if sample.uptime_seconds is not None else 'uptime —'
        self._text(10,217,f'{uptime} · {sample.architecture or "arch —"} · {sample.hardware.kernel_release or "kernel —"}',462,size=11,color=MUTED)
        if self.last_snapshot_at is not None and self.clock()-self.last_snapshot_at>3:
            self._text(315,176,'STALE',155,size=12,color=WARN)

    def process_view(self):
        processes=sorted_processes(getattr(self.snapshot,'processes',[]),self.sort)
        self.row=min(self.row,max(0,len(processes)-6))
        self._text(10,40,'PID       PROCESS',260,size=11,color=MUTED)
        self._text(284,40,'CPU %',80,size=11,color=ACCENT)
        self._text(388,40,'RAM %',80,size=11,color=ACCENT)
        if not processes:self._text(10,83,'No readable processes · requires Linux /proc',455,size=14)
        for i,p in enumerate(processes[self.row:self.row+6]):
            y=62+i*28
            self.canvas.create_rectangle(8,y-2,472,y+23,fill=CARD if i%2==0 else BACKGROUND,outline='',tags='dashboard')
            self._text(12,y,str(p.pid),63,size=12)
            self._text(82,y,p.name,195,size=13)
            self._text(284,y,percent(p.cpu),89,size=13)
            self._text(388,y,percent(p.memory),80,size=13)
        self._button((8,238,226,268),f'Sort: {self.sort} [S]')
        self._button((234,238,304,268),'↑ Pg')
        self._button((312,238,382,268),'↓ Pg')

    def network_view(self):
        sample=self.snapshot
        network=sample.network if sample else None
        item=network.primary if network else None
        self._text(10,44,('Connected · '+item.name) if item and item.state.upper()=='UP' else 'Disconnected / no local address',456,size=17,bold=True)
        address=', '.join((*item.addresses_v4,*item.addresses_v6)) if item else 'No configured address'
        self._text(10,73,address,456,size=12,color=MUTED)
        rates=getattr(sample,'network_rates',{}).get(item.name,(None,None)) if item else (None,None)
        for i,(label,value,history) in enumerate(zip(('Receive','Send'),rates,(self.rx_history,self.tx_history))):
            x=10+i*234
            self._text(x,103,label,222,size=12,color=ACCENT)
            self._text(x,128,'—' if value is None else f'{value/1024:.1f} KiB/s',222,size=20)
            self._sparkline(x,157,x+220,188,history.items(),ACCENT,percent=False)
        self._text(10,198,f'Hostname: {network.hostname if network else "unavailable"}',456,size=12)
        wifi=getattr(sample,'wireless',{}).get(item.name) if item else None
        detail=f'Wi-Fi quality {wifi[0]:.0f} · Signal {wifi[1]:.0f} dBm' if wifi else 'Interface details and system identity: 4 Diagnostics'
        self._text(10,218,detail,456,size=11,color=MUTED)

    def _detail_lines(self,name):
        lines=super()._detail_lines(name)
        if self.snapshot and name=='CPU':
            lines.extend([('Operating system',getattr(self.snapshot,'os_name','Unavailable')),
                          ('Runtime',getattr(self.snapshot,'runtime','Python / Tk'))])
        if self.snapshot and name=='Memory':
            for disk in getattr(self.snapshot,'disks',[]):
                if disk:lines.append((disk.label+' storage',f'{disk.percent:.1f}% used · {mib(disk.free)} free / {mib(disk.total)} total'))
        return lines

    def save_report(self):
        if not self.snapshot:return
        # Explicit fields only: never dump environment, process command lines or credentials.
        lines=['System Monitor diagnostics',f'OS: {getattr(self.snapshot,"os_name","Unavailable")}',getattr(self.snapshot,'runtime','')]
        for name in ('CPU','Memory','Temperature','GPU','Network'):
            lines.append('\n'+name)
            for heading,value in self._detail_lines(name):lines.append(f'{heading}: {value}')
        for disk in getattr(self.snapshot,'disks',[]):
            if disk:lines.append(f'{disk.label}: {mib(disk.free)} free / {mib(disk.total)} total')
        target=self.paths.documents/f'Diagnostics-{time.time_ns()}.txt'
        try:
            warning=atomic_write(target,lambda stream:stream.write('\n'.join(lines).encode()))
            self.report_status=warning or 'Report saved in Documents'
        except (OSError,ValueError):self.report_status='Report could not be saved'
        self._render()
