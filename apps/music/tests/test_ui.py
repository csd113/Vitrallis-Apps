from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from main import APP_ID, App
from player import Track
from storage import Paths


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve()
        self.root=tk.Tk()
        self.app=App(self.root,Paths(APP_ID,{'HOME':str(self.base)}))
        self.addCleanup(self.app.close)
        self.root.update()
        end=time.monotonic()+2
        while self.app.worker and self.app.worker.is_alive() and time.monotonic()<end:
            self.root.update();time.sleep(.01)
        self.app.tick();self.root.update()
        self.root.focus_force();self.app.listbox.focus_set();self.root.update()

    def key(self,key,char='',state=0):
        return self.app.key(SimpleNamespace(keysym=key,char=char,state=state))

    def test_native_geometry_keyboard_discovery_folder_empty_and_exit(self):
        self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(480,272))
        for child in self.root.winfo_children():
            if child.winfo_ismapped():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(),480)
                self.assertLessEqual(child.winfo_y()+child.winfo_height(),272)
        self.key('question','?');self.assertIn('folders',self.app.footer.cget('text'))
        self.key('f','f');self.assertEqual(self.app.view,'folders')
        self.key('Escape');self.assertEqual(self.app.view,'library')
        self.key('s','s');self.assertTrue(self.app.shuffle)
        self.key('t','t');self.assertEqual(self.app.repeat,'all')
        self.key('plus','+');self.assertEqual(self.app.player.volume,75)
        self.key('Escape');self.assertTrue(self.app.closed)
        self.assertTrue((self.app.paths.state/'settings.json').exists())

    def test_track_screen_missing_art_and_long_metadata(self):
        self.app.track=Track(self.base/'example.wav','A long title '*30,'A long artist '*20,'Album '*40,60)
        self.app.show_track();self.root.update()
        self.assertEqual(self.app.view,'now')
        self.assertEqual(self.app.now.winfo_height(),130)
        self.key('Escape');self.assertEqual(self.app.view,'library')

    def test_pointer_select_and_keyboard_play_share_action(self):
        self.app.tracks=[self.base/'example.wav'];self.app.fill()
        self.app.listbox.selection_set(0);self.app.selected()
        with patch.object(self.app,'work') as worker:
            self.app.listbox.focus_set();self.key('Return')
            worker.assert_called_once()
        self.assertEqual(self.app.index,0)

    def test_volume_surface_keyboard_and_touch_share_player_control(self):
        self.key('v','v');self.root.update()
        self.assertEqual(self.app.view,'volume')
        self.key('Right');self.assertEqual(self.app.player.volume,75)
        self.app.volume_scale.set(20)
        self.app.volume_scale.event_generate('<ButtonRelease-1>',x=30,y=30)
        self.root.update();self.assertEqual(self.app.player.volume,20)
        self.key('Escape');self.assertEqual(self.app.view,'library')

    def test_long_now_playing_text_does_not_overlap(self):
        self.app.track=Track(self.base/'long.wav','W'*160,'W'*160,'W'*160,60)
        self.app.show_track();self.root.update()
        texts=[self.app.now.bbox(i) for i in self.app.now.find_all() if self.app.now.type(i)=='text' and self.app.now.coords(i)[0]==134]
        for box in texts:
            self.assertLessEqual(box[2],460)
            self.assertLessEqual(box[3],130)
        self.assertLess(texts[0][3],texts[1][1]);self.assertLess(texts[1][3],texts[2][1])
