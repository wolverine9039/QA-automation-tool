"""Shared fixtures: a local HTTP server with routes for every link outcome."""
import copy
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

REDIRECTS = {
    "/r301": (301, "/ok"),
    "/r302": (302, "/ok"),
    "/r307": (307, "/ok"),
    "/chain1": (301, "chain2"),  # relative Location on purpose
    "/chain2": (301, "/ok"),
    "/loop1": (302, "/loop2"),
    "/loop2": (302, "/loop1"),
    "/to404": (301, "/missing"),
}
STATUSES = {"/ok": 200, "/missing": 404, "/gone": 410, "/ot404": 490, "/error": 500, "/forbidden": 403}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _route(self):
        path = self.path.split("?")[0]
        if path in REDIRECTS:
            status, loc = REDIRECTS[path]
            return self._send(status, headers={"Location": loc})
        if path in STATUSES:
            return self._send(STATUSES[path], b"<html><body>status page</body></html>",
                              {"Content-Type": "text/html"})
        if path == "/slow":
            time.sleep(3)
            return self._send(200, b"slow")
        if path == "/head405":
            if self.command == "HEAD":
                return self._send(405)
            return self._send(200, b"ok")
        if path == "/challenge":
            return self._send(200, b"<html><script src='/_Incapsula_Resource?x=1'></script></html>",
                              {"Content-Type": "text/html"})
        if path.startswith("/fixtures/"):
            f = FIXTURES / path.removeprefix("/fixtures/")
            if f.is_file():
                return self._send(200, f.read_bytes(), {"Content-Type": "text/html; charset=utf-8"})
        return self._send(404, b"not found")

    do_GET = _route
    do_HEAD = _route


@pytest.fixture(scope="session")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/"


@pytest.fixture
def test_cfg():
    from engine.config import load_config
    cfg = copy.deepcopy(load_config())
    cfg["link_check"].update(timeout_ms=1000, retries=0)
    return cfg
