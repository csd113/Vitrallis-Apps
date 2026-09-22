from html.parser import HTMLParser
import http.client
import json
import os
import socket
import threading
import time
from collections import namedtuple
from urllib.parse import quote
from unittest.mock import patch

import re
import unittest
from pathlib import Path

from support import StorageCase, gif_bytes, png_bytes
from media import MAX_UPLOAD
from convert import ConversionError
from web_server import WEB, WebServer, MAX_DOWNLOAD


from support import WebCase


class ConversionsStub:
    """Deterministic stand-in for the real GIF converter's HTTP-facing contract."""

    def __init__(self, library):
        self.library = library
        self.started = []
        self.closed = False
        self.value = {"status": "idle", "message": "", "item": None, "replacement": None,
                      "name": "", "collection": None, "converter": ""}

    def snapshot(self):
        return dict(self.value)

    def start(self, cid, mid):
        items = {item["id"]: item for item in self.library.playlist(cid)}
        item = items[mid]  # KeyError -> 404, matching the real converter.
        if item["kind"] != "gif":
            raise ConversionError("Only GIF items can be converted", code=400)
        if self.value["status"] == "running":
            raise ConversionError("A GIF conversion is already running", code=409)
        self.started.append((cid, mid))
        self.value.update(status="running", message="Converting GIF to WebP…", item=mid,
                          name=item["name"], collection=cid, converter="gif2webp")
        return self.snapshot()

    def start_bulk(self, scope, kinds, replace=False, collection=None):
        if self.value["status"] == "running":
            raise ConversionError("A conversion is already running", code=409)
        self.bulk = (scope, list(kinds), bool(replace), collection)
        self.value.update(status="running", message="Converting", item=None,
                          name="", collection=collection, converter="pillow")
        return self.snapshot()

    def request_cancel(self):
        self.cancelled = True
        self.value.update(status="cancelled", message="Conversion cancelled")

    def close(self):
        self.closed = True


class WebTests(WebCase):
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
        self.assertEqual(self.request("PUT", "/api/settings", {"image_seconds": 2, "repeats": 1, "order": "shuffle", "loop": False, "convert_gifs": True})[0], 200)
        self.assertEqual(self.settings.snapshot()["order"], "shuffle")
        self.assertTrue(self.settings.snapshot()["convert_gifs"])
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

    def test_two_upload_slots_allow_parallel_upload_and_bound_third(self):
        connection = self.begin_partial_upload()
        try:
            self.assertEqual(self.upload()[0], 201)
            # The response can arrive before the worker's finally block releases
            # its slot. Wait for that completion, then occupy the second slot.
            self.assertTrue(self.server.upload_slot.acquire(timeout=2))
            try:
                self.assertEqual(self.upload()[0], 409)
            finally:
                self.server.upload_slot.release()
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

    def test_state_reports_conversion_snapshot_and_download_limit(self):
        status, data, _ = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(data["max_download"], MAX_DOWNLOAD)
        self.assertEqual(set(data["conversion"]), {"status", "message", "item", "replacement",
                                                   "name", "collection", "converter", "job"})
        self.assertEqual(data["conversion"]["status"], "idle")
        self.assertEqual(data["conversion"]["job"]["status"], "idle")
        self.assertEqual(data["server"]["state"], "ready")
        self.assertEqual(data["capabilities"]["acceleration"]["policy"], "auto")

    def test_close_closes_conversions_before_processes(self):
        closed = []
        stub = ConversionsStub(self.library)
        stub.close = lambda: closed.append("conversions")
        self.server.conversions = stub
        with patch.object(self.server.processes, "close",
                          side_effect=lambda: closed.append("processes")):
            self.server.close()
        self.assertEqual(closed, ["conversions", "processes"])

    def test_convert_route_statuses_and_unknown_items(self):
        stub = ConversionsStub(self.library)
        self.server.conversions = stub
        gif = self.upload("animation.gif", gif_bytes())[1]
        png = self.upload("image.png", png_bytes())[1]
        route = f"/api/collections/{self.cid}/media/{{}}/convert"
        status, snapshot, _ = self.request("POST", route.format(gif["id"]))
        self.assertEqual(status, 202)
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["item"], gif["id"])
        self.assertEqual(stub.started, [(self.cid, gif["id"])])
        self.assertEqual(self.request("POST", route.format(png["id"]))[0], 400)
        self.assertEqual(self.request("POST", route.format(gif["id"]))[0], 409)
        self.assertEqual(self.request("POST", route.format("0" * 32))[0], 404)
        self.assertEqual(self.request("POST", "/api/collections/not-an-id/media/" + gif["id"] + "/convert")[0], 400)

    def test_bulk_convert_route_validates_scope_kinds_and_replace(self):
        stub = ConversionsStub(self.library)
        self.server.conversions = stub
        status, snapshot, _ = self.request("POST", "/api/convert", {
            "scope": "collection", "collection": self.cid, "kinds": ["gif"], "replace": False})
        self.assertEqual(status, 202)
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(stub.bulk, ("collection", ["gif"], False, self.cid))
        self.assertEqual(self.request("POST", "/api/convert", {
            "scope": "all", "kinds": ["gif", "image"], "replace": True})[0], 409)
        for body in ({"scope": "elsewhere", "kinds": ["gif"]},
                     {"scope": "collection", "collection": "not-an-id", "kinds": ["gif"]},
                     {"scope": "all", "kinds": []},
                     {"scope": "all", "kinds": ["video"]},
                     {"scope": "all", "kinds": ["gif"], "replace": "yes"},
                     {"scope": "all", "kinds": ["gif"], "extra": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/convert", body)[0], 400)

    def test_bulk_convert_cancel_route_requests_cancellation(self):
        stub = ConversionsStub(self.library)
        self.server.conversions = stub
        self.request("POST", "/api/convert", {"scope": "all", "kinds": ["image"]})
        status, snapshot, _ = self.request("POST", "/api/convert/cancel", {})
        self.assertEqual(status, 202)
        self.assertTrue(stub.cancelled)
        self.assertEqual(snapshot["status"], "cancelled")

    def test_bulk_conversion_uses_the_real_engine_over_http(self):
        self.request("POST", f"/api/collections/{self.cid}/media?name=clip.gif",
                     gif_bytes(), headers={"Content-Type": "application/octet-stream"})
        self.request("POST", "/api/convert", {
            "scope": "collection", "collection": self.cid, "kinds": ["gif"]})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            _, data, _ = self.request("GET", "/api/state")
            if data["conversion"]["job"]["status"] not in ("queued", "running"):
                break
            time.sleep(.05)
        job = data["conversion"]["job"]
        self.assertEqual(job["status"], "completed", job["message"])
        self.assertEqual(job["completed"], 1)
        self.assertEqual([row["kind"] for row in self.library.playlist(self.cid)], ["webp"])

    def test_upload_auto_converts_gifs_when_setting_is_on(self):
        stub = ConversionsStub(self.library)
        self.server.conversions = stub
        config = self.settings.snapshot()
        config["convert_gifs"] = True
        self.assertEqual(self.request("PUT", "/api/settings", config)[0], 200)
        status, item, _ = self.upload("animation.gif", gif_bytes())
        self.assertEqual(status, 201)
        self.assertEqual(stub.started, [(self.cid, item["id"])])
        self.assertEqual(item["conversion"]["status"], "running")
        self.assertEqual(self.upload()[0], 201)  # A still image never starts a conversion.
        self.assertEqual(len(stub.started), 1)

    def test_upload_rejects_when_staging_space_is_low(self):
        usage = namedtuple("usage", "total used free")
        with patch("web_server.shutil.disk_usage", return_value=usage(0, 0, 16 * 1024 * 1024 - 1)):
            status, data, _ = self.upload()
        self.assertEqual(status, 507)
        self.assertIn("free space", data["error"])
        self.assertEqual(list(self.paths.uploads.iterdir()), [])


class WebAssetTests(unittest.TestCase):
    """The shipped page, stylesheet and script must still agree with each other."""

    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")
        cls.css = (WEB / "style.css").read_text(encoding="utf-8")
        cls.js = (WEB / "app.js").read_text(encoding="utf-8")

    def test_every_element_id_is_unique_and_present_for_the_script(self):
        ids = re.findall(r'id="([^"]+)"', self.html)
        self.assertEqual(len(ids), len(set(ids)), "duplicate element ids")
        used = set(re.findall(r'\$\("([^"]+)"\)', self.js))
        self.assertEqual(sorted(used - set(ids)), [], "script reads missing element ids")
        self.assertEqual(sorted(set(re.findall(r'id="([^"]+)"', self.html)) - used - {
            "collections-view", "folder-view", "convert-view", "settings-view",
            "login-title", "login-help", "convert-heading", "upload-heading",
            "library-convert-heading", "settings-title"}), [],
            "unreferenced element ids")

    def test_the_content_security_policy_has_no_inline_script_or_style_to_catch(self):
        self.assertNotIn("style=", self.html)
        self.assertNotRegex(self.html, r"<\w+[^>]*\son[a-z]+=")
        for script in re.findall(r"<script([^>]*)>", self.html):
            self.assertIn('src="/app.js"', script)
        self.assertEqual(re.findall(r"<style", self.html), [])

    def test_every_bulk_conversion_action_is_offered_by_name(self):
        labels = re.findall(r'data-kinds="([^"]+)"', self.html)
        self.assertIn("gif", labels)
        self.assertIn("image", labels)
        self.assertIn("gif,image", labels)
        # Both the per-collection and the library-wide views offer all three.
        for kinds in ("gif", "image", "gif,image"):
            self.assertGreaterEqual(labels.count(kinds), 2, kinds)
        for text in ("Convert GIFs", "Convert images", "Convert all supported"):
            self.assertGreaterEqual(self.html.count(text), 2, text)

    def test_progress_reporting_names_every_count_the_job_maintains(self):
        for element in ("job-progress", "job-state", "job-scope", "job-total", "job-done",
                        "job-failed", "job-skipped", "job-message", "job-cancel",
                        "job-details", "job-failures"):
            self.assertIn('id="%s"' % element, self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_the_hidden_workspace_and_destructive_actions_stay_explicit(self):
        self.assertIn("Delete collection", self.html)
        self.assertIn("confirm(", self.js)
        # Every interactive control is a real button so keyboard users can reach it.
        self.assertNotRegex(self.html, r"<div[^>]*onclick")

class WebAccessibilityTests(unittest.TestCase):
    """Structural checks that stand in for eyeballing: names, labels and targets."""

    @classmethod
    def setUpClass(cls):
        cls.parser = None
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")
        cls.elements = []
        outer = cls

        class Collector(HTMLParser):
            def handle_starttag(self, tag, attrs):
                outer.elements.append((tag, dict(attrs)))

            def handle_startendtag(self, tag, attrs):
                outer.elements.append((tag, dict(attrs)))

        Collector().feed(cls.html)

    def attributes(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]

    def test_every_control_has_an_accessible_name(self):
        labelled = set(re.findall(r'<label[^>]*for="([^"]+)"', self.html))
        for attrs in self.attributes("input"):
            if attrs.get("type") in ("hidden",):
                continue
            name = attrs.get("aria-label") or attrs.get("id") in labelled
            self.assertTrue(name, "unlabelled input %r" % attrs)
        for attrs in self.attributes("select"):
            self.assertTrue(attrs.get("aria-label") or attrs.get("id") in labelled,
                            "unlabelled select %r" % attrs)
        for attrs in self.attributes("button"):
            self.assertNotIn("onclick", attrs)

    def test_every_button_has_visible_text_or_an_aria_label(self):
        for match in re.finditer(r"<button([^>]*)>(.*?)</button>", self.html, re.S):
            attributes, inner = match.group(1), match.group(2).strip()
            self.assertTrue("aria-label" in attributes or inner,
                            "unnamed button: %s" % match.group(0)[:90])
        for attrs in self.attributes("img"):
            self.assertIn("alt", attrs)

    def test_bulk_actions_are_labelled_and_not_icon_only(self):
        for match in re.finditer(r'<button[^>]*data-kinds="([^"]+)"[^>]*>([^<]+)</button>', self.html):
            self.assertTrue(match.group(2).strip(), match.group(1))

    def test_responsive_and_focus_styles_exist(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(":focus-visible", css)
        self.assertIn("overflow-wrap:anywhere", css)
        self.assertIn("@media (max-width:580px)", css)
        self.assertIn("button:disabled", css)

    def test_dangerous_actions_are_marked_and_confirmed(self):
        danger = [attrs for attrs in self.attributes("button") if attrs.get("class") == "danger"]
        self.assertTrue(danger)
        js = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("confirm(", js)
        self.assertIn("Delete collection", self.html)
