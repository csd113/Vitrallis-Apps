from html.parser import HTMLParser
import http.client
import json
import os
import socket
import threading
import time
from urllib.parse import quote
from unittest.mock import patch

from support import StorageCase, gif_bytes, png_bytes
from media import MAX_UPLOAD
from web_server import WebServer


class WebTests(StorageCase):
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

    def test_public_assets_auth_private_state_and_no_token_disclosure(self):
        status, body, headers = self.request("GET", "/", authorized=False)
        self.assertEqual(status, 200)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request("GET", "/api/state", authorized=False)[0], 401)
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertNotIn("token", data)
        self.assertEqual(data["collections"][0]["name"], "Unsorted")

    def test_six_character_access_code_login(self):
        self.assertRegex(self.server.token, r"^[0-9a-f]{6}$")
        self.assertEqual(self.request("GET", "/api/state")[0], 200)
        wrong_code = ("0" if self.server.token[0] != "0" else "1") + self.server.token[1:]
        for code in (wrong_code, self.server.token[:-1], self.server.token + "0" * 10):
            with self.subTest(code_length=len(code)):
                status, _, _ = self.request("GET", "/api/state",
                    headers={"Authorization": "Bearer " + code})
                self.assertEqual(status, 401)

    def test_login_field_requires_six_characters(self):
        fields = []

        class LoginParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == "input" and attributes.get("id") == "access-code":
                    fields.append(attributes)

        status, body, _ = self.request("GET", "/", authorized=False)
        self.assertEqual(status, 200)
        LoginParser().feed(body.decode("utf-8"))
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["minlength"], "6")
        self.assertEqual(fields[0]["maxlength"], "6")
        self.assertEqual(fields[0]["placeholder"], "6-character code")

    def test_unauthorized_mutations_have_no_storage_effect(self):
        before = self.library.path.read_bytes()
        routes = [("POST", "/api/collections"), ("PUT", "/api/settings"),
                  ("DELETE", f"/api/collections/{self.cid}"),
                  ("POST", f"/api/collections/{self.cid}/media?name=test.png")]
        for method, path in routes:
            self.assertEqual(self.request(method, path, {"name": "Evil"}, authorized=False)[0], 401)
        self.assertEqual(self.library.path.read_bytes(), before)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_cross_origin_and_rebinding_hosts_rejected(self):
        for headers in ({"Origin": "http://evil.example"}, {"Host": "evil.example"}, {"Origin": "null"}):
            self.assertEqual(self.request("POST", "/api/collections", {"name": "x"}, headers=headers)[0], 403)

    def test_path_traversal_no_package_or_arbitrary_files(self):
        for path in ("/../app.toml", "/%2e%2e/app.toml", "/web/../main.py", "/main.py", "/media/test.png", "/etc/passwd"):
            self.assertIn(self.request("GET", path)[0], (400, 404))
        for name in ("../evil.png", "/tmp/evil.png", "a\\b.png", "C:evil.png"):
            self.assertEqual(self.upload(name)[0], 400)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_create_rename_batch_upload_reorder_delete_and_settings(self):
        status, row, _ = self.request("POST", "/api/collections", {"name": "Trips"})
        self.assertEqual(status, 201)
        self.cid = row["id"]
        self.assertEqual(self.request("PUT", f"/api/collections/{self.cid}", {"name": "Gallery"})[0], 200)
        a = self.upload("image with spaces.png")
        b = self.upload("animation.gif", gif_bytes())
        self.assertEqual((a[0], b[0]), (201, 201))
        self.assertEqual(self.request("PUT", f"/api/collections/{self.cid}/order", {"ids": [b[1]["id"], a[1]["id"]]})[0], 200)
        self.assertEqual(self.library.playlist(self.cid)[0]["kind"], "gif")
        self.assertEqual(self.request("DELETE", f"/api/collections/{self.cid}/media/{a[1]['id']}")[0], 200)
        self.assertEqual(len(self.library.playlist(self.cid)), 1)
        self.assertEqual(self.request("PUT", "/api/settings", {"image_seconds": 2, "repeats": 1, "order": "shuffle", "loop": False})[0], 200)
        self.assertEqual(self.settings.snapshot()["order"], "shuffle")
        self.assertEqual(self.request("DELETE", f"/api/collections/{self.cid}")[0], 200)
        self.assertEqual(list(self.paths.media.iterdir()), [])

    def test_actual_format_validation_and_corrupt_rejection(self):
        # Extension is only display text; actual PNG bytes determine accepted type.
        status, result, _ = self.upload("photo.jpg")
        self.assertEqual(status, 201)
        self.assertEqual(result["kind"], "png")
        for raw in (b"<html>not media</html>", png_bytes()[:40]):
            self.assertEqual(self.upload(raw=raw)[0], 400)
        self.assertEqual(len(self.library.playlist(self.cid)), 1)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_oversized_upload_rejected_before_staging(self):
        status, _, _ = self.request("POST", f"/api/collections/{self.cid}/media?name=x.png", b"",
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(MAX_UPLOAD+1)})
        self.assertEqual(status, 413)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_duplicate_length_and_chunked_upload_rejected(self):
        for extra in ("Content-Length: 10\r\nContent-Length: 11", "Content-Length: 10\r\nTransfer-Encoding: chunked"):
            with socket.create_connection(("127.0.0.1", self.server.port), timeout=3) as connection:
                request = (f"POST /api/collections/{self.cid}/media?name=x.png HTTP/1.1\r\n"
                           f"Host: 127.0.0.1:{self.server.port}\r\nAuthorization: Bearer {self.server.token}\r\n"
                           f"Content-Type: application/octet-stream\r\n{extra}\r\n\r\n")
                connection.sendall(request.encode())
                self.assertIn(b"411", connection.recv(1024))

    def begin_partial_upload(self):
        connection = socket.create_connection(("127.0.0.1", self.server.port), timeout=3)
        request = (f"POST /api/collections/{self.cid}/media?name=x.png HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{self.server.port}\r\nAuthorization: Bearer {self.server.token}\r\n"
                   "Content-Type: application/octet-stream\r\nContent-Length: 100000\r\n\r\npartial")
        connection.sendall(request.encode())
        deadline = time.monotonic() + 2
        while not list(self.paths.uploads.iterdir()) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(list(self.paths.uploads.iterdir()))
        return connection

    def test_interrupted_upload_cleanup(self):
        connection = self.begin_partial_upload()
        connection.shutdown(socket.SHUT_RDWR)
        connection.close()
        deadline = time.monotonic() + 3
        while list(self.paths.uploads.iterdir()) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])
        self.assertEqual(self.library.playlist(self.cid), [])

    def test_single_upload_slot_rejects_parallel_upload(self):
        connection = self.begin_partial_upload()
        try:
            self.assertEqual(self.upload()[0], 409)
            self.assertEqual(self.request("GET", "/api/state")[0], 200)
        finally:
            connection.close()

    def test_shutdown_during_upload_restart_and_fresh_token(self):
        connection = self.begin_partial_upload()
        old_token, port = self.server.token, self.server.port
        self.server.close()
        connection.close()
        self.assertFalse(self.server.thread.is_alive())
        self.assertEqual(list(self.paths.uploads.iterdir()), [])
        self.assertFalse(self.server.http.workers)
        replacement = WebServer(self.library, self.settings, "127.0.0.1", port)
        replacement.start()
        self.addCleanup(replacement.close)
        self.assertNotEqual(old_token, replacement.token)

    def test_worker_cap_and_close_stalled_headers(self):
        connections = [socket.create_connection(("127.0.0.1", self.server.port), timeout=2) for _ in range(7)]
        try:
            for connection in connections:
                try:
                    connection.sendall(b"GET / HTTP/1.1\r\n")
                except OSError:
                    pass
            time.sleep(.05)
            self.assertLessEqual(len(self.server.http.workers), 4)
            self.server.close()
            self.assertFalse(self.server.http.workers)
        finally:
            for connection in connections:
                connection.close()

    def test_upload_failure_cleans_staging(self):
        with patch("web_server.probe", side_effect=ValueError("Invalid image")):
            self.assertEqual(self.upload()[0], 400)
        self.assertEqual(list(self.paths.uploads.iterdir()), [])

    def test_overall_deadline_closes_slow_dripped_headers(self):
        connection = socket.create_connection(("127.0.0.1", self.server.port), timeout=2)
        try:
            connection.sendall(b"GET / HTTP/1.1\r\n")
            deadline = time.monotonic() + 2
            while not self.server.http.sockets and time.monotonic() < deadline:
                time.sleep(.01)
            with self.server.http.worker_lock:
                self.assertTrue(self.server.http.sockets)
                for accepted in self.server.http.sockets:
                    self.server.http.sockets[accepted] = 0
            self.server.http.service_actions()
            self.assertEqual(connection.recv(1024), b"")
        finally:
            connection.close()

    def test_rate_limit_and_valid_code_still_works(self):
        for _ in range(30):
            self.assertFalse(self.server.authenticated("Bearer wrong"))
        self.assertEqual(self.request("GET", "/api/state", headers={"Authorization": "Bearer wrong"})[0], 429)
        self.assertEqual(self.request("GET", "/api/state")[0], 200)

    def test_non_ascii_authorization_is_rejected_without_crashing_worker(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Authorization": "Bearer café"})[0], 401)
        self.assertEqual(self.request("GET", "/api/state")[0], 200)
