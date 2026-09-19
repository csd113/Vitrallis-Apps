"""Four bounded HTTP workers, two streamed uploads, per-launch bearer access."""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
from socketserver import ThreadingMixIn
import subprocess
import threading
import time
import tempfile
import zipfile
from urllib.parse import parse_qs, urlsplit

from library import display_name, identifier
from media import MAX_UPLOAD, Processes, capabilities, probe
from storage import unique_keys
from previews import Thumbnails
from dependencies import Installation

WEB = Path(__file__).resolve().parent / "web"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}


def lan_addresses():
    """Read local interface configuration without contacting an Internet host."""
    command = [shutil.which("hostname"), "-I"] if sys_platform_linux() else [shutil.which("ifconfig")]
    if not command[0]:
        return []
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=2, check=False, text=True)
        candidates = result.stdout.split() if sys_platform_linux() else [
            line.split()[1] for line in result.stdout.splitlines() if line.strip().startswith("inet ")]
        addresses = []
        for value in candidates[:128]:
            try:
                ip = ipaddress.IPv4Address(value)
                if ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    addresses.append(str(ip))
            except ValueError:
                continue
        return sorted(set(addresses))
    except (OSError, subprocess.SubprocessError):
        return []


def sys_platform_linux():
    import sys
    return sys.platform.startswith("linux")


class HTTPError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class BoundedServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = False
    block_on_close = False
    request_queue_size = 4

    def __init__(self, address, owner):
        self.owner = owner
        self.slots = threading.BoundedSemaphore(4)
        self.worker_lock = threading.Lock()
        self.sockets = {}
        self.workers = set()
        super().__init__(address, Handler)

    def verify_request(self, request, client_address):
        return ipaddress.ip_address(client_address[0]).is_private

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self.worker_lock:
            self.sockets[request] = time.monotonic() + 160
        try:
            super().process_request(request, client_address)
        except BaseException:
            with self.worker_lock:
                self.sockets.pop(request, None)
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        thread = threading.current_thread()
        with self.worker_lock:
            self.workers.add(thread)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.worker_lock:
                self.sockets.pop(request, None)
                self.workers.discard(thread)
            self.slots.release()

    def service_actions(self):
        # Bound even slow-dripped HTTP headers, which socket idle timeouts alone
        # cannot constrain. No per-request watchdog threads are needed.
        with self.worker_lock:
            expired = [connection for connection, deadline in self.sockets.items()
                       if time.monotonic() >= deadline]
        for connection in expired:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class WebServer:
    def __init__(self, library, settings, host="0.0.0.0", port=8765):
        self.library, self.settings = library, settings
        self.token = secrets.token_hex(3)
        self.host, self.port = host, port
        self.name = socket.gethostname()[:64]
        self.http = None
        self.thread = None
        self.address_thread = None
        self.processes = Processes()
        self.upload_slot = threading.BoundedSemaphore(2)
        self.media_slot = threading.Lock()  # One expensive decoder across both uploads.

        self.thumbnails = Thumbnails(library, self.processes, self.media_slot)
        self.download_slot = threading.Lock()
        self.stopping = threading.Event()
        self.urls = []
        self.state = "Starting"
        self.installation = Installation()
        self.auth_lock = threading.Lock()
        self.auth_window = 0
        self.auth_failures = 0

    def start(self):
        if self.http is not None or self.stopping.is_set():
            raise RuntimeError("Server already started or stopped")
        try:
            self.http = BoundedServer((self.host, self.port), self)
        except OSError as error:
            import errno
            if self.port != 8765 or error.errno != errno.EADDRINUSE:
                raise
            self.http = BoundedServer((self.host, 0), self)
        self.port = self.http.server_port
        self.refresh_addresses()
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": 0.1},
                                       name="carousel-http")
        self.thread.start()

        self.address_thread = threading.Thread(target=self.watch_addresses, name="carousel-address")
        self.address_thread.start()

    def watch_addresses(self):
        while not self.stopping.wait(10):
            self.refresh_addresses()

    def refresh_addresses(self):
        addresses = lan_addresses() if self.host == "0.0.0.0" else [self.host]
        self.urls = [f"http://{address}:{self.port}" for address in addresses]
        if not self.urls:
            self.urls = [f"http://127.0.0.1:{self.port}"]
            self.state = "Local only address · check Wi-Fi"
        else:
            self.state = "Ready"

    def authenticated(self, header):
        valid = (isinstance(header, str) and header.isascii()
                 and hmac.compare_digest(header, "Bearer " + self.token))
        if valid:
            return True
        with self.auth_lock:
            now = time.monotonic()
            if now - self.auth_window >= 60:
                self.auth_window, self.auth_failures = now, 0
            self.auth_failures += 1
            if self.auth_failures > 30:
                raise HTTPError(429, "Too many invalid access codes; wait a minute")
        return False

    def close(self):
        self.stopping.set()
        if self.address_thread is not None:
            self.address_thread.join(timeout=3)
        if self.http is None:
            self.processes.close()
            return
        if self.thread is not None:
            self.http.shutdown()
            self.thread.join(timeout=2)
        with self.http.worker_lock:
            sockets = list(self.http.sockets)
        for connection in sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.processes.close()
        self.http.server_close()
        with self.http.worker_lock:
            workers = list(self.http.workers)
        deadline = time.monotonic() + 4
        for worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in workers):
            raise RuntimeError("HTTP worker did not stop within 4 seconds")
        self.state = "Stopped"


class Handler(BaseHTTPRequestHandler):
    server_version = "VitrallisCarousel"
    sys_version = ""
    protocol_version = "HTTP/1.0"  # Exactly one request per connection; no pipelining ambiguity.

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format_string, *args):
        pass  # Avoid logging tokens, user filenames and query strings.

    @property
    def owner(self):
        return self.server.owner

    def reply(self, code, payload, content_type="application/json; charset=utf-8"):
        if not isinstance(payload, bytes):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                         "frame-ancestors 'none'; form-action 'self'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PUT(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()

    def dispatch(self):
        try:
            if self.owner.stopping.is_set():
                raise HTTPError(503, "Server stopping")
            if len(self.path) > 2048:
                raise HTTPError(414, "Request path too long")
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or ".." in parsed.path or "\\" in parsed.path or "%" in parsed.path:
                raise HTTPError(400, "Invalid request path")
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise HTTPError(400, "One Host header is required")
            host = urlsplit("http://" + hosts[0])
            try:
                valid_host = (host.port == self.owner.port and not host.username and not host.path
                              and ipaddress.ip_address(host.hostname).is_private)
            except (ValueError, TypeError):
                valid_host = False
            if not valid_host:
                raise HTTPError(403, "Use the device IP address displayed in the app")
            origins = self.headers.get_all("Origin", [])
            if origins and origins != ["http://" + hosts[0]]:
                raise HTTPError(403, "Cross-origin requests are not allowed")
            if self.command == "GET" and parsed.path in ASSETS and not parsed.query:
                filename, mime = ASSETS[parsed.path]
                self.reply(200, (WEB / filename).read_bytes(), mime)
                return
            authorization = self.headers.get_all("Authorization", [])
            if len(authorization) != 1 or not self.owner.authenticated(authorization[0]):
                raise HTTPError(401, "Enter the access code displayed on the device")
            self.api(parsed)
        except HTTPError as error:
            self.safe_error(error.code, str(error))
        except KeyError:
            self.safe_error(404, "Collection or file no longer exists; refresh the page")
        except (ValueError, RecursionError) as error:
            self.safe_error(400, str(error)[:200])
        except (TimeoutError, ConnectionError):
            self.safe_error(408, "Transfer interrupted or timed out")
        except OSError:
            self.safe_error(507, "Storage or connection failure; check free space and permissions")

    def safe_error(self, code, message):
        try:
            self.reply(code, {"error": message})
        except (OSError, ValueError):
            pass  # The peer may already have disconnected; upload cleanup is in finally.

    def content_length(self, maximum):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise HTTPError(411, "One explicit Content-Length is required")
        length = int(lengths[0])
        if not 1 <= length <= maximum:
            raise HTTPError(413, f"Request too large (maximum {maximum} bytes)")
        return length

    def json_body(self):
        length = self.content_length(65536)
        if self.headers.get("Content-Type") != "application/json":
            raise HTTPError(415, "Expected application/json")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise HTTPError(400, "Incomplete request body")
        result = json.loads(raw, object_pairs_hook=unique_keys)
        if not isinstance(result, dict):
            raise HTTPError(400, "Expected a JSON object")
        return result

    def api(self, parsed):
        parts = parsed.path.strip("/").split("/")
        library, settings = self.owner.library, self.owner.settings
        if self.command == "GET" and parsed.path == "/api/state":
            self.reply(200, {"collections": library.snapshot(), "settings": settings.snapshot(),
                            "device": self.owner.name, "urls": self.owner.urls, "status": self.owner.state,
                            "capabilities": capabilities(blocking=False), "installation": self.owner.installation.snapshot(), "max_upload": MAX_UPLOAD,
                            "warning": library.warning or settings.warning})
        elif self.command == "POST" and parsed.path == "/api/dependencies/install":
            if self.json_body() != {"install": "ffmpeg"}:
                raise ValueError("Expected explicit FFmpeg installation request")
            self.reply(202, self.owner.installation.start())
        elif self.command == "PUT" and parsed.path == "/api/settings":
            self.reply(200, settings.save(self.json_body()))
        elif self.command == "POST" and parsed.path == "/api/collections":
            body = self.json_body()
            if set(body) != {"name"}:
                raise ValueError("Expected a collection name")
            self.reply(201, library.create(body["name"]))
        elif len(parts) >= 3 and parts[:2] == ["api", "collections"]:
            cid = identifier(parts[2])
            if len(parts) == 3 and self.command == "PUT":
                body = self.json_body()
                if set(body) != {"name"}:
                    raise ValueError("Expected a collection name")
                library.rename(cid, body["name"])
                self.reply(200, {"ok": True})
            elif len(parts) == 3 and self.command == "DELETE":
                library.delete(cid)
                self.reply(200, {"ok": True})
            elif len(parts) == 4 and parts[3] == "order" and self.command == "PUT":
                body = self.json_body()
                if set(body) != {"ids"}:
                    raise ValueError("Expected an ordered ID list")
                library.reorder(cid, body["ids"])
                self.reply(200, {"ok": True})
            elif len(parts) == 4 and parts[3] == "download" and self.command == "GET":
                self.download(cid)
            elif len(parts) == 6 and parts[3] == "media" and parts[5] == "thumbnail" and self.command == "GET":
                mid = identifier(parts[4])
                item = next((item for item in library.playlist(cid) if item['id'] == mid), None)
                if item is None:
                    raise KeyError(mid)
                self.reply(200, self.owner.thumbnails.get(item), 'image/png')
            elif len(parts) == 4 and parts[3] == "media" and self.command == "POST":
                self.upload(cid, parsed.query)
            elif len(parts) == 5 and parts[3] == "media" and self.command == "DELETE":
                library.delete(cid, identifier(parts[4]))
                self.reply(200, {"ok": True})
            else:
                raise HTTPError(404, "Unknown API route")
        else:
            raise HTTPError(404, "Unknown API route")

    def download(self, cid):
        items = self.owner.library.playlist(cid)
        # Keep one bounded, unlinked staging archive on data storage, not a
        # potentially RAM-backed /tmp. Disconnect and every error close it.
        maximum = 256 * 1024 * 1024
        if sum(item['size'] for item in items) > maximum:
            raise HTTPError(413, "Collection exceeds the 256 MiB download limit")
        if not self.owner.download_slot.acquire(blocking=False):
            raise HTTPError(409, "Another folder download is active")
        try:
            with tempfile.TemporaryFile(dir=self.owner.library.paths.data) as temporary:
                names = set()
                with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as archive:
                    for item in items:
                        if self.owner.stopping.is_set():
                            raise HTTPError(503, "Server stopping")
                        name = display_name(item['name'], 160)
                        # Duplicate display names are valid in the existing library;
                        # preserve each original basename in a distinct ID directory.
                        member = name if name.casefold() not in names else item['id'] + '/' + name
                        names.add(name.casefold())
                        with self.owner.library.open_item(item) as source:
                            if os.fstat(source.fileno()).st_size != item['size']:
                                raise ValueError("Media size changed; refresh the collection")
                            with archive.open(member, 'w') as target:
                                remaining = item['size']
                                while remaining:
                                    chunk = source.read(min(65536, remaining))
                                    if not chunk:
                                        raise ValueError("Media changed during download")
                                    target.write(chunk)
                                    remaining -= len(chunk)
                length = temporary.tell()
                temporary.seek(0)
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename="collection.zip"')
                self.send_header('Content-Length', str(length))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                shutil.copyfileobj(temporary, self.wfile, 65536)
        finally:
            self.owner.download_slot.release()

    def upload(self, cid, query):
        length = self.content_length(MAX_UPLOAD)
        if self.headers.get("Content-Type") != "application/octet-stream":
            raise HTTPError(415, "Upload a raw file using application/octet-stream")
        names = parse_qs(query, strict_parsing=True, max_num_fields=1)
        if set(names) != {"name"} or len(names["name"]) != 1:
            raise ValueError("One filename is required")
        name = display_name(names["name"][0], 160)
        self.owner.library.playlist(cid)  # Reject unknown collections before writing bytes.
        if not self.owner.upload_slot.acquire(blocking=False):
            raise HTTPError(409, "Two uploads are active; retry when one finishes")
        temporary = None
        try:
            stream, temporary = self.owner.library.temporary_upload()
            with stream:
                remaining, deadline = length, time.monotonic() + 120
                while remaining:
                    if self.owner.stopping.is_set() or time.monotonic() > deadline:
                        raise HTTPError(408, "Upload exceeded the 120-second deadline")
                    chunk = self.rfile.read1(min(65536, remaining))
                    if not chunk:
                        raise HTTPError(400, "Incomplete upload")
                    stream.write(chunk)
                    remaining -= len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            with self.owner.media_slot:
                info = probe(temporary, self.owner.processes)
            if self.owner.stopping.is_set():
                raise HTTPError(503, "Server stopping")
            item = self.owner.library.add_upload(cid, name, temporary, info)
            self.reply(201, item)
        finally:
            if temporary is not None and os.path.lexists(temporary):
                temporary.unlink()
            self.owner.upload_slot.release()
