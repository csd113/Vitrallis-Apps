import importlib.util
from pathlib import Path
import sys
import unittest
import tkinter as tk

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
spec = importlib.util.spec_from_file_location('calculator_main', PACKAGE / 'main.py')
calculator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calculator)


class UITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = calculator.App(self.root)
        self.addCleanup(self.app.close)
        self.root.update()
        self.root.focus_force()
        self.app.buttons[4].focus_set()
        self.root.update()

    def key(self, key):
        self.root.focus_get().focus_force()
        self.root.update()
        self.root.focus_get().event_generate('<KeyPress>', keysym=key)
        self.root.update()

    def test_keyboard_navigation_arithmetic_and_exit(self):
        self.key('Right')
        self.assertIs(self.root.focus_get(), self.app.buttons[5])
        self.key('Down')
        self.assertIs(self.root.focus_get(), self.app.buttons[9])
        self.key('Return')
        self.assertEqual(self.app.model.expression, '5')
        for key in ('plus', '2', 'equal'): self.key(key)
        self.assertEqual(self.app.model.result, '7')
        self.key('BackSpace')
        self.assertEqual(self.app.model.expression, '5+')
        self.key('Escape')
        self.assertTrue(self.app.closed)

    def test_480_layout_and_long_result(self):
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (480, 272))
        for child in self.root.winfo_children():
            self.assertGreaterEqual(child.winfo_x(), 0)
            self.assertGreaterEqual(child.winfo_y(), 0)
            self.assertLessEqual(child.winfo_x()+child.winfo_width(), 480)
            self.assertLessEqual(child.winfo_y()+child.winfo_height(), 272)
        for key in '999999999999999999999999=': self.app.press(key)
        self.root.update()
        from tkinter.font import Font
        font = Font(root=self.root, font=self.app.result.cget('font'))
        self.assertLessEqual(font.measure(self.app.model.result), self.app.result.winfo_width())
        self.assertEqual(len(self.app.buttons), 20)
        self.assertEqual((self.app.icon.width(), self.app.icon.height()), (128, 128))
