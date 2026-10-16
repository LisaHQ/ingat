import contextlib
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ingat.adapters.http_probe import request
from ingat.model.errors import Failed


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes, headers: list[tuple[str, str]]) -> None:
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/big":
            self._send(200, b"x" * 5000, [])
        elif self.path == "/redirect":
            self._send(302, b"", [("Location", "/elsewhere")])
        elif self.path == "/missing":
            self._send(404, b'{"error":"no"}', [("Content-Type", "application/json")])
        else:
            self._send(200, b'{"ok":true}', [("Content-Type", "application/json"), ("X-Multi", "a"), ("X-Multi", "b")])

    def do_POST(self) -> None:
        data = self.rfile.read(int(self.headers["Content-Length"]))
        echo = {"path": self.path, "body": data.decode(), "csrf": self.headers["X-Fx-CSRF"]}
        self._send(201, json.dumps(echo).encode(), [])


class HttpProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_get_returns_status_lowercased_headers_and_body(self) -> None:
        status, headers, body = request(self.port, "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["x-multi"], "a, b")
        self.assertEqual(json.loads(body), {"ok": True})

    def test_post_sends_method_headers_and_body(self) -> None:
        status, _, body = request(self.port, "/api/gate", method="POST", headers={"X-Fx-CSRF": "1"}, body="{}")
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body), {"path": "/api/gate", "body": "{}", "csrf": "1"})

    def test_error_status_and_redirect_are_returned_not_followed(self) -> None:
        self.assertEqual(request(self.port, "/missing")[0], 404)
        status, headers, _ = request(self.port, "/redirect")
        self.assertEqual((status, headers["location"]), (302, "/elsewhere"))

    def test_body_is_bounded(self) -> None:
        self.assertEqual(request(self.port, "/big", limit=100)[2], b"x" * 100)

    def test_no_listener_raises_failed(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with self.assertRaises(Failed) as cm:
            request(port, "/")
        self.assertEqual(cm.exception.code, "probe")

    def test_silent_server_times_out(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            with self.assertRaises(Failed):
                request(s.getsockname()[1], "/", timeout=0.3)

    def test_a_trickling_response_is_cut_at_the_deadline(self) -> None:
        srv = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(srv.close)
        stop = threading.Event()
        self.addCleanup(stop.set)

        def trickle() -> None:  # each byte arrives well within the per-read timeout; the whole body takes 50 s
            conn, _ = srv.accept()
            with conn, contextlib.suppress(OSError):
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                while not stop.wait(0.05):
                    conn.sendall(b"x")

        threading.Thread(target=trickle, daemon=True).start()
        started = time.monotonic()
        with self.assertRaises(Failed) as cm:
            request(srv.getsockname()[1], "/", timeout=0.5)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("within 0.5s", cm.exception.message)

    def test_an_invalid_request_raises_failed(self) -> None:
        for path, headers in (("/a b", {}), ("/", {"X-Bad": "a\r\nInjected: 1"})):
            with self.subTest(path=path), self.assertRaises(Failed):
                request(self.port, path, headers=headers)


if __name__ == "__main__":
    unittest.main()
