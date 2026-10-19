"""Tool-side HTTP probe client: host loopback only, bounded body and time (MANIFEST_SPEC §5)."""

import contextlib
import http.client
import socket
import threading
from collections.abc import Mapping

from ingat.model.errors import Failed


def request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: str | None = None,
    timeout: float = 5.0,
    limit: int = 1 << 20,
) -> tuple[int, dict[str, str], bytes]:
    """One request to 127.0.0.1:<port> that ends within `timeout`, no redirects followed. Header names are
    lower-cased and repeated headers joined with ", "; the body is cut at `limit` bytes. Raises Failed(code="probe")."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    expired = threading.Event()

    def expire() -> None:  # a server that trickles bytes would otherwise hold the caller forever
        expired.set()
        with contextlib.suppress(OSError, AttributeError):
            conn.sock.shutdown(socket.SHUT_RDWR)

    timer = threading.Timer(timeout, expire)
    timer.start()
    try:
        conn.request(method, path, None if body is None else body.encode(), dict(headers or {}))
        resp = conn.getresponse()
        out: dict[str, str] = {}
        for name, value in resp.getheaders():
            key = name.lower()
            out[key] = f"{out[key]}, {value}" if key in out else value
        data = resp.read(limit)
        if expired.is_set():  # the cut may have ended the body early
            raise TimeoutError
        return resp.status, out, data
    except (OSError, ValueError, http.client.HTTPException) as e:
        why = f"no complete response within {timeout}s" if expired.is_set() else e
        raise Failed(f"The web check {method} {path} on port {port} did not answer: {why}", code="probe") from e
    finally:
        timer.cancel()
        conn.close()
