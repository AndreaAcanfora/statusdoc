"""Minimal HTTP client: bounded size, bounded redirects, no downgrade from HTTPS."""

from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import __version__

USER_AGENT = f"statusdoc/{__version__} (+https://github.com/AndreaAcanfora/statusdoc)"
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class FetchError(Exception):
    """The request failed or returned an unusable response."""


Fetcher = Callable[[str], Response]


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if req.full_url.startswith("https:") and not newurl.startswith("https:"):
            raise FetchError(f"refusing redirect from HTTPS to {newurl.split(':', 1)[0]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirects)


def get(url: str, timeout: float = 10) -> Response:
    """GETs a URL. HTTP error statuses are returned, not raised."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            return _read(r, r.geturl(), r.status)
    except urllib.error.HTTPError as e:
        return _read(e, e.geturl() or url, e.code)
    except FetchError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        raise FetchError(f"{url}: {reason}") from None


def _read(r: Any, url: str, status: int) -> Response:
    raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise FetchError(f"{url}: response larger than {MAX_BYTES} bytes")
    headers = {k.lower(): v for k, v in r.headers.items()}
    if headers.get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
        if len(raw) > MAX_BYTES:
            raise FetchError(f"{url}: response larger than {MAX_BYTES} bytes")
    return Response(url=url, status=status, headers=headers, body=raw)
