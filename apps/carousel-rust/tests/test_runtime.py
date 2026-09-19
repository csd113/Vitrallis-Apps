"""Real isolated codec/animation parity. Set CAROUSEL_RUST_TEST_BINARY to a host build."""
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

try:
    from PIL import Image, ImageSequence
except ImportError:
    Image = None

BINARY = os.environ.get('CAROUSEL_RUST_TEST_BINARY')
PACKAGE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(BINARY and Image, 'requires host Rust build and Pillow parity oracle')
class CodecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_media(self, path, mode='--inspect', repeats=1):
        with path.open('rb') as stream:
            return subprocess.run([BINARY, mode, '480', '272', str(repeats)], stdin=stream,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=35)

    def frames(self, path, repeats=1):
        result = self.run_media(path, '--decode', repeats)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        data = io.BytesIO(result.stdout)
        frames = []
        while header := data.read(16):
            w, h, delay, count = struct.unpack('<IIII', header)
            self.assertEqual(count, w * h * 4)
            pixels = data.read(count)
            self.assertEqual(len(pixels), count)
            frames.append((Image.frombytes('RGBA', (w, h), pixels), delay))
        return frames

    def test_still_format_parity_orientation_and_signature_detection(self):
        for fmt, kind in [('PNG', 'png'), ('JPEG', 'jpeg'), ('WEBP', 'webp')]:
            with self.subTest(fmt=fmt):
                path = self.root / 'wrong.extension'
                image = Image.new('RGB', (12, 8), (200, 30, 50))
                options = {'exif': Image.Exif()} if fmt == 'JPEG' else {}
                if options: options['exif'][274] = 6
                image.save(path, format=fmt, **options)
                result = self.run_media(path)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(json.loads(result.stdout)['kind'], kind)
                decoded = self.frames(path)
                self.assertEqual(len(decoded), 1)
                self.assertEqual(decoded[0][0].size, (8, 12) if fmt == 'JPEG' else (12, 8))

    def test_gif_disposal_transparency_and_complete_replays(self):
        path = self.root / 'animation.gif'
        frames = []
        for x in range(3):
            frame = Image.new('RGBA', (24, 16), (0, 0, 0, 0))
            for y in range(4, 12):
                for col in range(x * 5, x * 5 + 4): frame.putpixel((col, y), (220, 80, 40, 255))
            frames.append(frame)
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=[0, 20, 150], loop=0, disposal=[1, 2, 3])
        actual = self.frames(path, repeats=3)
        self.assertEqual(len(actual), 9)
        self.assertEqual([delay for _, delay in actual], [100, 20, 150] * 3)
        with Image.open(path) as gif:
            expected = [frame.convert('RGBA').copy() for frame in ImageSequence.Iterator(gif)]
        for index, (frame, _) in enumerate(actual):
            # Transparent RGB values are not visible; compare over the black display.
            def black(image):
                result = Image.new('RGBA', image.size, (0, 0, 0, 255))
                result.alpha_composite(image)
                return result.tobytes()
            self.assertEqual(black(frame), black(expected[index % 3]))

    def test_rejects_animated_png_webp_corruption_and_pixel_bombs(self):
        for fmt in ('PNG', 'WEBP'):
            path = self.root / ('animated.' + fmt.lower())
            Image.new('RGB', (4, 4), 'red').save(path, format=fmt, save_all=True,
                append_images=[Image.new('RGB', (4, 4), 'blue')], duration=100, loop=0)
            self.assertNotEqual(self.run_media(path).returncode, 0)
        path = self.root / 'huge.png'
        Image.new('1', (4000, 2001)).save(path)
        self.assertNotEqual(self.run_media(path).returncode, 0)
        path.write_bytes(b'\x89PNG\r\n\x1a\ncorrupt')
        self.assertNotEqual(self.run_media(path).returncode, 0)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
    def test_real_vp8_vp9_webm_and_replay_output(self):
        for codec in ('vp8', 'vp9'):
            path = PACKAGE / 'assets' / f'capability-{codec}.webm'
            result = self.run_media(path)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(json.loads(result.stdout)['kind'], 'webm')
            once = self.frames(path)
            twice = self.frames(path, repeats=2)
            self.assertGreater(len(once), 0)
            self.assertEqual(len(twice), 2 * len(once))
            self.assertTrue(all(frame.size == (480, 272) and delay == 50 for frame, delay in twice))
