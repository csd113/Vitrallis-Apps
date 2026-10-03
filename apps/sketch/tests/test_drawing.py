from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drawing import Drawing, WIDTH, HEIGHT, HISTORY
from storage import Paths, atomic_write, validate_path, write_state, read_state


class DrawingTests(unittest.TestCase):
    def setUp(self):self.d=Drawing()

    def test_fast_stroke_interpolates_and_edges_clamp(self):
        self.d.begin(-4,-2);self.d.stroke(WIDTH+30,HEIGHT+20);self.d.end()
        self.assertNotEqual(self.d.image.getpixel((0,0)),(255,255,255))
        self.assertNotEqual(self.d.image.getpixel((WIDTH-1,HEIGHT-1)),(255,255,255))
        self.assertNotEqual(self.d.image.getpixel((WIDTH//2,HEIGHT//2)),(255,255,255))

    def test_undo_redo_and_bounded_many_strokes(self):
        original=self.d.image.tobytes()
        self.d.begin(10,10);self.d.stroke(30,20);self.d.end()
        drawn=self.d.image.tobytes()
        self.d.undo();self.assertEqual(self.d.image.tobytes(),original)
        self.d.undo(True);self.assertEqual(self.d.image.tobytes(),drawn)
        for i in range(200):self.d.begin(i,10);self.d.end()
        self.assertEqual(len(self.d.undo_stack),HISTORY)
        for _ in range(100):self.d.undo()
        self.assertFalse(self.d.undo())

    def test_eraser_clear_new(self):
        self.d.begin(10,10);self.d.end();self.d.eraser=True;self.d.begin(10,10);self.d.end()
        self.assertEqual(self.d.image.getpixel((10,10)),(255,255,255))
        self.d.clear();self.assertTrue(self.d.dirty);self.d.new();self.assertFalse(self.d.dirty)
        self.assertEqual(self.d.undo_stack,[])

    def test_png_save_reopen_and_atomic_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t).resolve()/'Drawing.png'
            self.d.begin(3,4);self.d.stroke(50,40);self.d.end();self.d.save(target)
            data=target.read_bytes();expected=self.d.image.tobytes()
            self.assertTrue(data.startswith(b'\x89PNG'))
            self.d.new();self.d.open(target);self.assertEqual(self.d.image.tobytes(),expected)
            self.d.clear()
            with patch('storage.os.replace',side_effect=OSError('interrupted')),self.assertRaises(OSError):self.d.save(target)
            self.assertEqual(target.read_bytes(),data)
            self.assertEqual(list(target.parent.glob('.saving-*')),[])
            self.assertTrue(self.d.dirty)

    def test_malformed_and_oversized_images_preserve_drawing(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t).resolve()/'bad.png';target.write_bytes(b'not png')
            original=self.d.image.tobytes()
            with self.assertRaises(ValueError):self.d.open(target)
            self.assertEqual(self.d.image.tobytes(),original)
            Image.new('RGB',(2200,2200)).save(target)
            with self.assertRaises(ValueError):self.d.open(target)

    def test_read_only_import_jpeg_converts_to_native_canvas(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve()/'input.jpg';Image.new('RGB',(100,100),'red').save(p);p.chmod(0o444)
            self.d.open(p)
            self.assertIsNone(self.d.path)
            self.assertEqual(self.d.image.size,(WIDTH,HEIGHT))
            self.assertEqual(self.d.image.getpixel((0,0)),(255,255,255))

    def test_save_denied_retains_dirty_content(self):
        with tempfile.TemporaryDirectory() as t:
            self.d.begin(1,1);self.d.end()
            with patch('storage.tempfile.mkstemp',side_effect=PermissionError('denied')),self.assertRaises(PermissionError):self.d.save(Path(t).resolve()/'out.png')
            self.assertTrue(self.d.dirty)


class StorageTests(unittest.TestCase):
    def test_launcher_documents_and_state_separation(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();docs=root/'documents'/'io.vitrallis.sketch'
            paths=Paths('io.vitrallis.sketch',{'HOME':str(root),'VITRALLIS_DOCUMENTS_DIR':str(docs),'VITRALLIS_APP_ID':'io.vitrallis.sketch'})
            self.assertFalse(docs.exists())
            d=Drawing();d.save(docs/'new.png')
            write_state(paths.state/'settings.json',{'color':3})
            self.assertEqual(read_state(paths.state/'settings.json'),{'color':3})
            self.assertEqual(paths.documents,docs)
            self.assertEqual(paths.state.stat().st_mode & 0o777,0o700)
            self.assertEqual(paths.data.stat().st_mode & 0o777,0o700)
            self.assertNotEqual(paths.documents,paths.state)

    def test_invalid_paths_do_not_create_any_directories(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();link=root/'link';link.symlink_to(root,target_is_directory=True)
            for value in ('relative','/tmp/../unsafe',str(link/'data'),str(Path(__file__).resolve().parents[1]/'user-data')):
                with self.subTest(value=value),self.assertRaises(ValueError):Paths('io.vitrallis.sketch',{'HOME':str(root),'VITRALLIS_DOCUMENTS_DIR':value})
            self.assertEqual(len(list(root.iterdir())),1)
            with self.assertRaises(ValueError):Paths('io.vitrallis.sketch',{'HOME':str(root),'VITRALLIS_APP_ID':'io.other.app'})

    def test_save_rejects_link_fifo_and_package_directory(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();p=root/'link';p.symlink_to(root/'outside')
            with self.assertRaises(ValueError):atomic_write(p,lambda f:f.write(b'test'))
            with self.assertRaises(ValueError):validate_path(Path(__file__).resolve().parents[1]/'save.png')


class DurabilityTests(unittest.TestCase):
    def test_directory_sync_failure_reports_committed_save(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t).resolve()/'Drawing.png';drawing=Drawing();drawing.begin(0,0);drawing.end()
            with patch('storage.os.fsync',side_effect=[None,OSError('directory sync denied')]):drawing.save(path)
            self.assertTrue(path.exists());self.assertFalse(drawing.dirty)
            self.assertIn('durability',drawing.warning)
            reopened=Drawing();reopened.open(path)
            self.assertEqual(reopened.image.tobytes(),drawing.image.tobytes())


class BrushTests(unittest.TestCase):
    def test_one_pixel_brush_has_one_pixel_dot(self):
        drawing=Drawing();drawing.size=0;drawing.begin(10,10);drawing.end()
        colored=sum(drawing.image.getpixel((x,y))!=(255,255,255) for y in range(HEIGHT) for x in range(WIDTH))
        self.assertEqual(colored,1)
