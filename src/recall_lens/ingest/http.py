"""HTTP client for agency APIs: retries with backoff and per-host rate limiting.

Deliberately stdlib-only; the ingestion workload is a few hundred sequential requests.
"""

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "recall-lens/0.1 (+https://github.com/coder-raj369/recall-lens)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Minimum seconds between requests to one host. openFDA allows 240 requests/minute without a key.
MIN_INTERVAL = {"api.fda.gov": 0.3}
DEFAULT_MIN_INTERVAL = 0.5

_last_request: dict[str, float] = {}

# A host whose requests keep failing is skipped for a while, so a check does not wait minutes on
# a lookup service that is down and ingestion moves on to the next agency sooner.
BREAKER_FAILURES = 3  # consecutive failed requests that open a host's circuit
BREAKER_COOLDOWN = 60.0  # seconds before one trial request is let through
_failures: dict[str, int] = {}
_open_until: dict[str, float] = {}


class CircuitOpen(ConnectionError):
    """The host failed repeatedly and is skipped until its cooldown ends."""


def _wait_turn(host: str) -> None:
    interval = MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)
    elapsed = time.monotonic() - _last_request.get(host, float("-inf"))
    if elapsed < interval:
        time.sleep(interval - elapsed)
    _last_request[host] = time.monotonic()


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    return float(value) if value and value.isdigit() else None


def fetch(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    retries: int = 4,
    backoff: float = 1.0,
    timeout: float = 60,
) -> bytes:
    """GET a URL, retrying transient failures with exponential backoff."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    parts = urllib.parse.urlsplit(url)
    if time.monotonic() < _open_until.get(parts.netloc, 0.0):
        raise CircuitOpen(f"{parts.netloc} keeps failing; skipped until its cooldown ends")
    try:
        body = _get(url, parts.hostname or "", retries=retries, backoff=backoff, timeout=timeout)
    except urllib.error.HTTPError as error:
        if error.code in RETRY_STATUSES:
            _failed(parts.netloc)
        else:
            _failures.pop(parts.netloc, None)  # the host answered
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
        _failed(parts.netloc)
        raise
    _failures.pop(parts.netloc, None)
    return body


def _failed(netloc: str) -> None:
    _failures[netloc] = _failures.get(netloc, 0) + 1
    if _failures[netloc] >= BREAKER_FAILURES:
        _open_until[netloc] = time.monotonic() + BREAKER_COOLDOWN


def _get(url: str, host: str, *, retries: int, backoff: float, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        _wait_turn(host)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUSES or attempt == retries:
                raise
            delay = _retry_after(error) or backoff * 2**attempt
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            # HTTPException covers IncompleteRead: a connection dropped mid-body.
            if attempt == retries:
                raise
            delay = backoff * 2**attempt
        time.sleep(delay)
    raise AssertionError("unreachable")


def get_json(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return json.loads(fetch(url, params, **kwargs))
