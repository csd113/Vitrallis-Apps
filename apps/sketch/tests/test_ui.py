from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from main import APP_ID, App
from storage import Paths
from drawing import WIDTH,HEIGHT


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.root=tk.Tk()
        self.app=App(self.root,Paths(APP_ID,{'HOME':str(self.base)}));self.addCleanup(self.app.close)
        self.root.update();self.root.focus_force();self.app.canvas.focus_set();self.root.update()

    def key(self,key,char='',state=0):return self.app.key(SimpleNamespace(keysym=key,char=char,state=state))

    def test_pointer_mapping_fast_strokes_and_edge_of_screen(self):
        c=self.app.canvas
        c.event_generate('<ButtonPress-1>',x=0,y=0)
        for i in range(100):c.event_generate('<B1-Motion>',x=i*5,y=i*3)
        c.event_generate('<ButtonRelease-1>',x=WIDTH-1,y=HEIGHT-1)
        self.root.update();self.app.render()
        self.assertNotEqual(self.app.model.image.getpixel((0,0)),(255,255,255))
        self.assertNotEqual(self.app.model.image.getpixel((WIDTH-1,HEIGHT-1)),(255,255,255))
        self.assertIsNone(self.app.model.last)
        self.assertEqual(len(self.app.model.undo_stack),1)
        self.assertEqual((c.winfo_x(),c.winfo_y()),(8,40))

    def test_keyboard_draw_tool_size_color_undo_redo_and_exit(self):
        self.key('space',' ');self.key('Right');self.key('Down');self.key('space',' ')
        self.assertTrue(self.app.model.dirty)
        self.key('e','e');self.assertTrue(self.app.model.eraser)
        self.key('plus','+');self.assertEqual(self.app.model.size,2)
        self.key('3','3');self.assertEqual(self.app.model.color,2)
        self.assertFalse(self.app.model.eraser)
        self.key('u','u');self.assertFalse(self.app.model.undo_stack)
        self.key('y','y');self.assertTrue(self.app.model.undo_stack)
        self.key('Escape');self.assertEqual(self.app.dialog_kind,'confirm')
        self.key('Escape');self.assertIsNone(self.app.overlay)
        self.app.model.dirty=False;self.key('Escape');self.assertTrue(self.app.closed)

    def test_save_as_open_and_overwrite_confirmation(self):
        self.key('s','s',1);self.assertEqual(self.app.dialog_kind,'save')
        self.app.filename.delete(0,'end');self.app.filename.insert(0,'Sketch.png');self.app.save_named()
        target=self.app.paths.documents/'Sketch.png';self.assertTrue(target.exists())
        self.key('o','o');self.assertEqual(self.app.dialog_kind,'open')
        self.app.open_selected();self.assertEqual(self.app.model.path,target)
        self.key('s','s',1);self.app.save_named()
        self.assertIn('Already exists',self.app.message.cget('text'))
        self.app.save_named(True);self.assertIsNone(self.app.overlay)

    def test_dialogs_and_toolbar_fit_native_resolution(self):
        self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(480,272))
        for child in self.root.winfo_children():
            if child.winfo_ismapped():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(),480)
                self.assertLessEqual(child.winfo_y()+child.winfo_height(),272)
        self.app.save(True);self.root.update()
        self.assertLessEqual(self.app.overlay.winfo_x()+self.app.overlay.winfo_width(),480)
        self.assertLessEqual(self.app.overlay.winfo_y()+self.app.overlay.winfo_height(),272)

    def test_term_recovery_is_external_to_package(self):
        self.app.model.begin(5,5);self.app.model.end();self.app.terminate()
        self.assertEqual(len(list(self.app.paths.documents.glob('Recovery-*.png'))),1)
        self.assertTrue(self.app.closed)
