import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hello_main', PACKAGE / 'main.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class AppTests(unittest.TestCase):
    def test_resources_and_launch_ignore_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(PACKAGE / 'main.py'), '--check'],
                                    cwd=directory, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'Hello, Vitrallis!\n')

    def test_import_has_no_io_or_window(self):
        module = importlib.util.module_from_spec(spec)
        with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected I/O')):
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))

    def test_missing_asset_is_actionable(self):
        output = io.StringIO()
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError('greeting.txt')):
            with contextlib.redirect_stderr(output):
                self.assertEqual(app.main(['--check']), 1)
        self.assertIn('Cannot read bundled greeting', output.getvalue())

    def test_invalid_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(app.main(['--unknown']), 2)


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.tk = tk
            self.root = tk.Tk()
        except ImportError as error:
            if os.environ.get('VITRALLIS_REQUIRE_GUI') == '1':
                raise
            self.skipTest(f'Tk unavailable: {error}')
        except tk.TclError as error:
            if os.environ.get('VITRALLIS_REQUIRE_GUI') == '1':
                raise
            self.skipTest(f'Tk/display unavailable: {error}')
        self.addCleanup(self.close_root)

    def close_root(self):
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass

    def test_icon_decodes_and_widgets_fit(self):
        icon = self.tk.PhotoImage(file=str(PACKAGE / 'icon.png'))
        self.assertEqual((icon.width(), icon.height()), (128, 128))
        label, home = app.build_window(self.root, self.tk)
        self.root.update()
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (480, 272))
        self.assertEqual(label.cget('text'), 'Hello, Vitrallis!')
        for widget in (label, home):
            self.assertGreaterEqual(widget.winfo_x(), 0)
            self.assertGreaterEqual(widget.winfo_y(), 0)
            self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), 480)
            self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), 272)
            self.assertLessEqual(widget.winfo_reqwidth(), widget.winfo_width())
        self.assertGreaterEqual(home.winfo_height(), 36)
        home.invoke()
        with self.assertRaises(self.tk.TclError):
            self.root.winfo_exists()

    def test_keyboard_exit(self):
        _, home = app.build_window(self.root, self.tk)
        self.root.update()
        self.root.focus_force()
        home.focus_set()
        self.root.update()
        self.assertEqual(self.root.focus_get(), home)
        home.event_generate('<Return>')
        with self.assertRaises(self.tk.TclError):
            self.root.winfo_exists()

    def test_escape_exit(self):
        app.build_window(self.root, self.tk)
        self.root.update()
        self.root.focus_force()
        self.root.update()
        self.root.event_generate('<Escape>')
        with self.assertRaises(self.tk.TclError):
            self.root.winfo_exists()


if __name__ == '__main__':
    unittest.main()
