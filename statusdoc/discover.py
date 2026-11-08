"""Finding the status document of a service (SPEC.md, section 3)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any
from urllib.parse import urlsplit

from .adapters import detect, load
from .fetch import Fetcher, FetchError, Response, get
from .model import Document


@dataclass
class Discovery:
    target: str
    document_url: str
    #: How the document was found: well-known, registry, convention or url.
    method: str
    document: Document
    page_url: str | None = None
    response: Response | None = None


class DiscoveryError(Exception):
    def __init__(self, target: str, attempts: list[tuple[str, str]]):
        self.target = target
        self.attempts = attempts
        tried = "; ".join(f"{url} ({why})" for url, why in attempts)
        super().__init__(f"no status document found for {target}: tried {tried}")


def load_registry() -> dict[str, dict[str, str]]:
    data = json.loads(resources.files("statusdoc").joinpath("registry.json").read_text("utf-8"))
    return data["services"]


_DOMAIN = re.compile(r"^[A-Za-z0-9.-]+(:\d+)?$")


def discover(target: str, *, fetch: Fetcher = get, registry: dict[str, dict[str, str]] | None = None, scheme: str = "https") -> Discovery:
    """Finds and reads the status document of a domain, a status page URL or a document URL."""
    if "://" in target:
        return _from_url(target, fetch)
    domain = target.strip().lower().rstrip(".")
    if not _DOMAIN.match(domain):
        raise ValueError(f"not a domain or URL: {target!r}")
    domain = domain.removeprefix("www.")
    attempts: list[tuple[str, str]] = []

    # 1. The service's own well-known URI.
    well_known = f"{scheme}://{domain}/.well-known/status"
    data, resp = _try_json(well_known, fetch, attempts)
    if isinstance(data, dict):
        if detect(data):
            return Discovery(target, resp.url, "well-known", load(data), response=resp)
        doc_url = data.get("document")
        if isinstance(doc_url, str) and doc_url.startswith(("https://", f"{scheme}://")):
            found = _try_document(doc_url, fetch, attempts)
            if found:
                page = data.get("page") if isinstance(data.get("page"), str) else None
                return Discovery(target, found[1].url, "well-known", found[0], page_url=page, response=found[1])
        else:
            attempts.append((well_known, "no document URL"))

    # 2. The list of known services, for the domain and its parents.
    reg = load_registry() if registry is None else registry
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        entry = reg.get(".".join(parts[i:]))
        if entry:
            found = _try_document(entry["document"], fetch, attempts)
            if found:
                return Discovery(target, found[1].url, "registry", found[0], page_url=entry.get("page"), response=found[1])
            break

    # 3. Common conventions.
    host = domain.split(":")[0]
    label = host.split(".")[-2] if host.count(".") >= 1 else host
    for page in (f"{scheme}://status.{domain}", f"{scheme}://{label}status.com", f"{scheme}://www.{label}status.com"):
        for path in ("/api/v2/summary.json", "/index.json"):
            found = _try_document(page + path, fetch, attempts)
            if found:
                return Discovery(target, found[1].url, "convention", found[0], page_url=page, response=found[1])
    raise DiscoveryError(target, attempts)


def _from_url(url: str, fetch: Fetcher) -> Discovery:
    attempts: list[tuple[str, str]] = []
    found = _try_document(url, fetch, attempts)
    if found:
        return Discovery(url, found[1].url, "url", found[0], response=found[1])
    # A status page URL: try the usual document paths.
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    for path in ("/api/v2/summary.json", "/index.json"):
        found = _try_document(base + path, fetch, attempts)
        if found:
            return Discovery(url, found[1].url, "convention", found[0], page_url=url, response=found[1])
    raise DiscoveryError(url, attempts)


def _try_json(url: str, fetch: Fetcher, attempts: list[tuple[str, str]]) -> tuple[Any, Response]:
    try:
        resp = fetch(url)
    except FetchError as e:
        attempts.append((url, str(e).removeprefix(url + ": ")))
        return None, Response(url, 0)
    if resp.status != 200:
        attempts.append((url, f"HTTP {resp.status}"))
        return None, resp
    try:
        return resp.json(), resp
    except (ValueError, UnicodeDecodeError):
        attempts.append((url, "not JSON"))
        return None, resp


def _try_document(url: str, fetch: Fetcher, attempts: list[tuple[str, str]]) -> tuple[Document, Response] | None:
    data, resp = _try_json(url, fetch, attempts)
    if data is None:
        return None
    if not detect(data):
        attempts.append((url, "JSON, but not a status document"))
        return None
    return load(data), resp
