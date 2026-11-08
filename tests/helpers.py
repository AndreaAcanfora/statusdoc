import copy
import json
from pathlib import Path

from statusdoc.fetch import FetchError, Response

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))


GOOD_HEADERS = {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "cache-control": "max-age=30",
    "etag": '"abc"',
}


def minimal(**overrides) -> dict:
    """A small valid OSD document."""
    doc = {
        "osd_version": "0.1",
        "page": {"name": "Example", "url": "https://status.example.com", "updated_at": "2026-11-08T10:00:00Z"},
        "status": {"indicator": "none", "description": "All Systems Operational"},
        "components": [
            {"id": "grp", "name": "Core", "status": "operational", "group": True, "updated_at": "2026-11-08T10:00:00Z"},
            {"id": "api", "name": "API", "status": "operational", "group_id": "grp", "updated_at": "2026-11-08T10:00:00Z"},
            {"id": "web", "name": "Website", "status": "operational", "group_id": None, "updated_at": "2026-11-08T10:00:00Z"},
        ],
        "incidents": [],
        "scheduled_maintenances": [],
    }
    doc.update(copy.deepcopy(overrides))
    return doc


def incident(**overrides) -> dict:
    inc = {
        "id": "inc1",
        "name": "Elevated errors",
        "status": "investigating",
        "impact": "major",
        "created_at": "2026-11-08T09:00:00Z",
        "updated_at": "2026-11-08T09:30:00Z",
        "incident_updates": [
            {"id": "u2", "status": "identified", "body": "Found it.", "created_at": "2026-11-08T09:30:00Z"},
            {"id": "u1", "status": "investigating", "body": "Looking.", "created_at": "2026-11-08T09:00:00Z"},
        ],
        "components": [{"id": "api", "name": "API", "status": "partial_outage"}],
    }
    inc.update(overrides)
    return inc


class FakeWeb:
    """A fetcher that serves canned responses and records requests."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list[str] = []

    def __call__(self, url: str) -> Response:
        self.requests.append(url)
        r = self.routes.get(url)
        if r is None:
            return Response(url, 404, {"content-type": "text/plain"}, b"not found")
        if isinstance(r, Exception):
            raise r
        if isinstance(r, Response):
            return r
        body = r if isinstance(r, bytes) else json.dumps(r).encode()
        return Response(url, 200, dict(GOOD_HEADERS), body)


def unreachable(url: str) -> FetchError:
    return FetchError(f"{url}: connection refused")
