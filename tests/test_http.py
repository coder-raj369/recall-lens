import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from recall_lens.ingest import http


def serve(responses):
    """Serve the given (status, body) pairs in order on a local port."""
    queue = list(responses)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = queue.pop(0)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, queue


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(http, "DEFAULT_MIN_INTERVAL", 0)


def test_retries_transient_errors_then_succeeds():
    server, queue = serve([(503, b""), (429, b""), (200, b'{"ok": true}')])
    url = f"http://127.0.0.1:{server.server_port}/"
    assert http.get_json(url, {"q": "a b"}, backoff=0) == {"ok": True}
    assert queue == []
    server.shutdown()


def test_does_not_retry_client_errors():
    server, queue = serve([(404, b""), (200, b"{}")])
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        http.fetch(f"http://127.0.0.1:{server.server_port}/", backoff=0)
    assert excinfo.value.code == 404
    assert len(queue) == 1
    server.shutdown()


def test_gives_up_after_retries():
    server, _ = serve([(500, b"")] * 3)
    with pytest.raises(urllib.error.HTTPError):
        http.fetch(f"http://127.0.0.1:{server.server_port}/", retries=2, backoff=0)
    server.shutdown()
