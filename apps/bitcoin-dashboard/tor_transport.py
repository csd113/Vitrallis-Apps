"""Use the Shell's loopback SOCKS5 service, with remote DNS and no fallback."""
from http.client import HTTPSConnection
import os
import socket
import ssl
import time
from urllib.request import HTTPSHandler


def proxy_config():
    if 'VITRALLIS_TOR_API' not in os.environ:
        return None
    if (os.environ.get('VITRALLIS_TOR_API') != '1'
            or os.environ.get('VITRALLIS_TOR_AVAILABLE') != '1'
            or os.environ.get('VITRALLIS_TOR_SOCKS_HOST') != '127.0.0.1'
            or os.environ.get('VITRALLIS_TOR_SOCKS_PORT') != '9150'):
        raise OSError('Shell Tor unavailable; no direct fallback')
    return ('127.0.0.1', 9150)


def exact(sock, count, deadline):
    result = bytearray()
    while len(result) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Tor handshake timed out')
        sock.settimeout(remaining)
        chunk = sock.recv(count-len(result))
        if not chunk:
            raise OSError('Tor connection closed')
        result.extend(chunk)
    return bytes(result)


def tunnel(host, port, timeout):
    proxy = proxy_config()
    if proxy is None:
        raise OSError('Shell Tor contract missing')
    name = host.encode('idna')
    if not 1 <= len(name) <= 255 or port != 443:
        raise OSError('Invalid Tor destination')
    deadline = time.monotonic() + timeout
    sock = socket.create_connection(proxy, timeout=timeout)
    try:
        sock.sendall(b'\x05\x01\x00')
        if exact(sock, 2, deadline) != b'\x05\x00':
            raise OSError('Tor authentication unsupported')
        sock.sendall(b'\x05\x01\x00\x03' + bytes([len(name)]) + name + port.to_bytes(2, 'big'))
        reply = exact(sock, 4, deadline)
        if reply[:3] != b'\x05\x00\x00':
            raise OSError('Tor destination unavailable')
        lengths = {1: 4, 4: 16}
        count = exact(sock, 1, deadline)[0] if reply[3] == 3 else lengths.get(reply[3])
        if count is None:
            raise OSError('Invalid Tor response')
        exact(sock, count + 2, deadline)
        sock.settimeout(max(0.001, deadline-time.monotonic()))
        return sock
    except BaseException:
        sock.close()
        raise


class TorHTTPSConnection(HTTPSConnection):
    def connect(self):
        sock = tunnel(self.host, self.port, self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class TorHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(TorHTTPSConnection, request)
