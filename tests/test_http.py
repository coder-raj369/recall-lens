import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from recall_lens.ingest import http


def serve(responses):
    """Serve (status, body) pairs in order; body None sends a truncated response."""
    queue = list(responses)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = queue.pop(0)
            self.send_response(status)
            if body is None:  # promise 100 bytes, send 2, then close the connection
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"{}")
                self.close_connection = True
                return
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
    monkeypatch.setattr(http, "_failures", {})  # every test starts with closed circuits
    monkeypatch.setattr(http, "_open_until", {})


def test_retries_transient_errors_then_succeeds():
    server, queue = serve([(503, b""), (429, b""), (200, b'{"ok": true}')])
    url = f"http://127.0.0.1:{server.server_port}/"
    assert http.get_json(url, {"q": "a b"}, backoff=0) == {"ok": True}
    assert queue == []
    server.shutdown()


def test_retries_truncated_responses():
    server, queue = serve([(200, None), (200, b'{"ok": true}')])
    assert http.get_json(f"http://127.0.0.1:{server.server_port}/", backoff=0) == {"ok": True}
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


def test_a_failing_host_is_skipped_until_a_trial_after_its_cooldown(monkeypatch):
    import time

    monkeypatch.setattr(http, "BREAKER_COOLDOWN", 0.2)
    server, queue = serve([(503, b"")] * 3 + [(200, b"{}")])
    url = f"http://127.0.0.1:{server.server_port}/"
    for _ in range(3):
        with pytest.raises(urllib.error.HTTPError):
            http.fetch(url, retries=0)
    with pytest.raises(http.CircuitOpen):
        http.fetch(url, retries=0)
    assert len(queue) == 1  # skipped without a request
    time.sleep(0.25)
    assert http.fetch(url, retries=0) == b"{}"  # the trial succeeds and closes the circuit
    assert http._failures == {}
    server.shutdown()
