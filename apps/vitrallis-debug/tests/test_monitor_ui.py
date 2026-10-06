from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from monitor_ui import Monitor
from demo import DemoCollector
from monitoring import Process, Disk
from storage import Paths


class MonitorUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.paths=Paths('io.vitrallis.debug',{'HOME':str(Path(self.temp.name).resolve())})
        self.root=tk.Tk();self.root.geometry('480x272')
        with patch('monitor_ui.Paths',return_value=self.paths):self.app=Monitor(self.root,tk,DemoCollector(),demo=True)
        self.addCleanup(self.app.close)
        self.app.snapshot=DemoCollector().collect()
        self.app.snapshot.processes=[Process(i,'Long process name '*12,10,20,4096,float(i),1.0) for i in range(30)]
        self.app.snapshot.disks=[Disk('Root',100,50,45)]
        self.app.snapshot.network_rates={'wlan-demo':(2048,1024)}
        self.app.last_snapshot_at=self.app.clock()
        self.root.update_idletasks();self.app._render()

    def key(self,name,char=''):return self.app._key(SimpleNamespace(keysym=name,char=char,state=0))

    def test_native_layout_keyboard_sections_sort_page_back_and_exit(self):
        self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(480,272))
        for section in ('1','2','3','4'):
            self.key(section,section)
            self.assertEqual(self.app.section_focus,int(section)-1)
        self.key('2','2');self.key('s','s');self.assertEqual(self.app.sort,'memory')
        self.key('Next');self.assertEqual(self.app.row,6)
        self.key('Escape');self.assertEqual(self.app.section,'Overview')
        self.key('Escape');self.assertTrue(self.app.closed)

    def test_touch_tabs_require_matching_press_release(self):
        press=lambda x,y:SimpleNamespace(x=x,y=y)
        self.app._press(press(130,12));self.app._release(press(130,12))
        self.assertEqual(self.app.section,'Processes')
        self.app._press(press(250,12));self.app._release(press(10,12))
        self.assertEqual(self.app.section,'Processes')

    def test_diagnostics_retains_gpu_details_and_saves_explicit_report(self):
        self.key('4','4');self.app._activate('GPU')
        self.assertEqual(self.app.model.expanded,4)
        self.key('s','s')
        files=list(self.paths.documents.glob('Diagnostics-*.txt'))
        self.assertEqual(len(files),1)
        report=files[0].read_text()
        self.assertIn('Counter source',report)
        self.assertNotIn('environ',report)
        self.assertNotIn('PASSWORD',report)
        self.key('Escape');self.assertIsNone(self.app.model.expanded)
        self.key('Escape');self.assertEqual(self.app.section,'Overview')

    def test_overview_and_process_text_is_bounded_at_native_resolution(self):
        for section in range(3):
            self.app.switch(section)
            for item in self.app.canvas.find_withtag('dashboard'):
                if self.app.canvas.type(item)=='text':
                    box=self.app.canvas.bbox(item)
                    self.assertGreaterEqual(box[0],0)
                    self.assertLessEqual(box[2],480)
                    self.assertGreaterEqual(box[1],0)
                    self.assertLessEqual(box[3],272)
        self.root.geometry('640x360');self.root.update_idletasks();self.app._render()
        self.assertEqual(self.root.winfo_width(),640)
