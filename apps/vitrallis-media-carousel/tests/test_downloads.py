"""Streamed collection downloads: no staging archive, no size surprises."""
import io
import zipfile
from unittest.mock import patch

from support import WebCase, gif_bytes, png_bytes
import web_server
from web_server import MAX_DOWNLOAD, archive_size


def route(cid):
    return f"/api/collections/{cid}/download"


class TruncatedSource:
    """A source that reports its real size but stops producing bytes early."""

    def __init__(self, stream, limit):
        self.stream, self.limit, self.served = stream, limit, 0

    def fileno(self):
        return self.stream.fileno()

    def read(self, size):
        allowed = min(size, max(0, self.limit - self.served))
        if not allowed:
            return b""
        chunk = self.stream.read(allowed)
        self.served += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.stream.close()


class DownloadTests(WebCase):
    def test_archive_round_trips_names_bytes_and_duplicates(self):
        self.assertEqual(self.upload("one.png")[0], 201)
        self.assertEqual(self.upload("one.png")[0], 201)
        self.assertEqual(self.upload("café 写真.png", gif_bytes())[0], 201)
        status, raw, headers = self.request("GET", route(self.cid))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        items = self.library.playlist(self.cid)
        self.assertEqual(len(items), 3)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.namelist()
            self.assertEqual(len(members), 3)
            self.assertIn("one.png", members)
            self.assertIn(items[1]["id"] + "/one.png", members)
            self.assertIn("café 写真.png", members)
            for item, member in zip(items, members):
                expected = gif_bytes() if item["kind"] == "gif" else png_bytes()
                self.assertEqual(archive.read(member), expected)

    def test_streamed_response_is_close_delimited_and_bounded(self):
        self.upload()
        status, raw, headers = self.request("GET", route(self.cid))
        self.assertEqual(status, 200)
        self.assertNotIn("Content-Length", headers)
        self.assertEqual(headers["Connection"], "close")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        bound = int(headers["X-Archive-Bytes"])
        self.assertEqual(bound, archive_size(self.library.playlist(self.cid)))
        self.assertLessEqual(len(raw), bound)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.namelist(), ["image.png"])
            self.assertEqual(archive.read("image.png"), png_bytes())

    def test_download_never_creates_a_temporary_archive(self):
        self.upload()
        with patch("tempfile.TemporaryFile", side_effect=AssertionError("temporary archive")), \
                patch("tempfile.NamedTemporaryFile", side_effect=AssertionError("temporary archive")):
            status, raw, _ = self.request("GET", route(self.cid))
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.namelist(), ["image.png"])

    def test_archive_size_covers_ascii_duplicate_and_utf8_members(self):
        self.add("plain.png")
        self.add("plain.png")
        self.add("café 写真.png")
        self.add("folder name with spaces %.png")
        items = self.library.playlist(self.cid)
        bound = archive_size(items)
        status, raw, headers = self.request("GET", route(self.cid))
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Archive-Bytes"], str(bound))
        self.assertLessEqual(len(raw), bound)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(len(archive.namelist()), 4)
            self.assertIn(items[1]["id"] + "/plain.png", archive.namelist())

    def test_download_limit_rejects_oversized_and_allows_the_boundary(self):
        self.upload()
        items = self.library.playlist(self.cid)
        bound = archive_size(items)
        with patch.object(web_server, "MAX_DOWNLOAD", bound - 1):
            status, data, _ = self.request("GET", route(self.cid))
        self.assertEqual(status, 413)
        self.assertIn("4 GiB", data["error"])
        self.assertTrue(self.server.download_slot.acquire(blocking=False))
        self.server.download_slot.release()
        with patch.object(web_server, "MAX_DOWNLOAD", bound):
            status, raw, headers = self.request("GET", route(self.cid))
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Archive-Bytes"], str(bound))
        self.assertLessEqual(len(raw), bound)

    def test_download_limit_rejects_large_metadata_without_files(self):
        fake = [{"id": "a" * 32, "name": "huge.png", "kind": "png", "size": MAX_DOWNLOAD}]
        with patch.object(self.library, "playlist", return_value=fake):
            status, data, _ = self.request("GET", route(self.cid))
        self.assertEqual(status, 413)
        self.assertIn("4 GiB", data["error"])
        self.assertTrue(self.server.download_slot.acquire(blocking=False))
        self.server.download_slot.release()

    def test_changed_source_fails_before_headers_and_releases_slot(self):
        items = [self.add("photo.png"), self.add("other.png")]
        path = self.paths.media / items[1]["id"]
        before = set(self.paths.data.iterdir())
        path.write_bytes(b"short")
        status, data, _ = self.request("GET", route(self.cid))
        self.assertEqual(status, 400)
        self.assertIn("size changed", data["error"])
        self.assertEqual(set(self.paths.data.iterdir()), before)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])
        self.assertTrue(self.server.download_slot.acquire(blocking=False))
        self.server.download_slot.release()

    def test_short_source_mid_stream_aborts_without_a_json_error(self):
        content = bytes(range(256)) * 800
        item = self.add("large.png", content=content)
        before = set(self.paths.data.iterdir())
        real_open = self.library.open_item
        with patch.object(self.library, "open_item",
                          side_effect=lambda row: TruncatedSource(real_open(row), 4096)):
            status, raw, headers = self.request("GET", route(self.cid))
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Archive-Bytes"], str(archive_size([item])))
        self.assertTrue(raw.startswith(b"PK\x03\x04"))
        self.assertLess(len(raw), item["size"])
        self.assertNotIn(b'{"error"', raw)
        self.assertNotIn(b"Media changed during download", raw)
        with self.assertRaises(zipfile.BadZipFile):
            zipfile.ZipFile(io.BytesIO(raw)).close()
        self.assertEqual(set(self.paths.data.iterdir()), before)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])
        self.assertTrue(self.server.download_slot.acquire(blocking=False))
        self.server.download_slot.release()
