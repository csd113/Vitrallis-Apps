import io
from pathlib import Path
import shutil
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


def webp_bytes(color="red", size=(64, 32)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="WEBP", quality=90, method=4)
    return stream.getvalue()


def gif_bytes(frames=3, duration=(40, 80, 120), loop=0, disposal=2, size=(48, 24)):
    stream = io.BytesIO()
    images = _animation_frames(frames, size)
    delays = _delays(duration, frames)
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:],
                   duration=delays, loop=loop, disposal=disposal)
    return stream.getvalue()


def animated_webp_bytes(frames=3, duration=(40, 80, 120), loop=0, size=(48, 24)):
    stream = io.BytesIO()
    images = _animation_frames(frames, size)
    images[0].save(stream, format="WEBP", save_all=True, append_images=images[1:],
                   duration=_delays(duration, frames), loop=loop, quality=90, method=4)
    return stream.getvalue()


def _animation_frames(count, size):
    colors = ("red", "blue", "green", "yellow", "purple", "orange")
    return [Image.new("RGBA", size, colors[index % len(colors)]) for index in range(count)]


def _delays(duration, count):
    delays = list(duration)
    return [delays[index % len(delays)] for index in range(count)]


def gif2webp_path():
    return shutil.which("gif2webp")


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


import http.client
import json
from urllib.parse import quote
from web_server import WebServer

class WebCase(StorageCase):
    def setUp(self):
        super().setUp()
        self.server = WebServer(self.library, self.settings, "127.0.0.1", 0)
        self.server.start()
        self.addCleanup(self.server.close)

    def request(self, method, path, body=None, authorized=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        supplied = {"Authorization": "Bearer " + self.server.token} if authorized else {}
        supplied.update(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            supplied["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=body, headers=supplied)
            response = connection.getresponse()
            raw = response.read()
            data = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
            return response.status, data, dict(response.getheaders())
        finally:
            connection.close()

    def upload(self, name="image.png", raw=None):
        return self.request("POST", f"/api/collections/{self.cid}/media?name={quote(name, safe='')}",
                            png_bytes() if raw is None else raw, headers={"Content-Type": "application/octet-stream"})
