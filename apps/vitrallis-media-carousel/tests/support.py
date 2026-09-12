import io
from pathlib import Path
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from PIL import Image
from library import Library
from settings import Settings
from storage import Paths


def png_bytes(color="red", size=(64, 32)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def gif_bytes():
    stream = io.BytesIO()
    frames = [Image.new("RGBA", (48, 24), color) for color in ("red", "blue", "green")]
    frames[0].save(stream, format="GIF", save_all=True, append_images=frames[1:],
                   duration=[40, 80, 120], loop=0, disposal=2)
    return stream.getvalue()


class StorageCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.paths = Paths({"HOME": str(self.base)})
        self.library = Library(self.paths)
        self.settings = Settings(self.paths.config)
        self.cid = self.library.snapshot()[0]["id"]

    def add(self, name="photo.png", content=None, kind="png"):
        stream, path = self.library.temporary_upload()
        with stream:
            stream.write(png_bytes() if content is None else content)
        return self.library.add_upload(self.cid, name, path, {"kind": kind})
