"""Strict checks of a status document and of how it is served (SPEC.md, sections 4 and 6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .fetch import Response
from .model import (
    COMPONENT_STATUSES,
    IMPACTS,
    INCIDENT_STATUSES,
    INDICATORS,
    MAINTENANCE_STATUSES,
    OSD_VERSION,
    impact_severity,
    indicator_severity,
)


@dataclass
class Issue:
    level: str  # "MUST" or "SHOULD"
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level:6} {self.path}: {self.message}"


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "MUST" for i in issues)


_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


class _Checker:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def must(self, path: str, message: str) -> None:
        self.issues.append(Issue("MUST", path, message))

    def should(self, path: str, message: str) -> None:
        self.issues.append(Issue("SHOULD", path, message))

    def obj(self, parent: dict[str, Any], key: str, path: str, required: bool = True) -> dict[str, Any] | None:
        v = parent.get(key)
        if isinstance(v, dict):
            return v
        if v is None and not required:
            return None
        self.must(f"{path}.{key}", "required object" if v is None else "must be an object")
        return None

    def string(self, parent: dict[str, Any], key: str, path: str, level: str = "MUST", nullable: bool = False) -> str | None:
        v = parent.get(key)
        if isinstance(v, str) and v:
            return v
        if v is None and (level == "OPTIONAL" or (nullable and key in parent)):
            return None
        if v is None or v == "":
            if level == "MUST":
                self.must(f"{path}.{key}", "required string")
            elif level == "SHOULD":
                self.should(f"{path}.{key}", "recommended")
            return None
        self.must(f"{path}.{key}", "must be a string")
        return None

    def time(self, parent: dict[str, Any], key: str, path: str, level: str = "MUST", nullable: bool = False) -> None:
        v = self.string(parent, key, path, level, nullable)
        if v is not None and not _valid_time(v):
            self.must(f"{path}.{key}", f"not an RFC 3339 timestamp: {v!r}")

    def enum(self, parent: dict[str, Any], key: str, path: str, allowed: tuple[str, ...]) -> str | None:
        v = self.string(parent, key, path)
        if v is not None and v not in allowed:
            self.should(f"{path}.{key}", f"{v!r} is not defined in OSD {OSD_VERSION} (expected one of {', '.join(allowed)})")
        return v


def _valid_time(v: str) -> bool:
    if not _RFC3339.match(v):
        return False
    try:
        datetime.fromisoformat(v.replace("z", "Z").replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_document(data: Any) -> list[Issue]:
    """Checks a parsed JSON document against section 4."""
    c = _Checker()
    if not isinstance(data, dict):
        c.must("$", "a status document is a JSON object")
        return c.issues
    if data.get("osd_version") is None:
        c.should("$.osd_version", f'recommended: "{OSD_VERSION}"')
    elif not isinstance(data["osd_version"], str):
        c.must("$.osd_version", "must be a string")

    page = c.obj(data, "page", "$")
    if page is not None:
        c.string(page, "name", "$.page")
        url = c.string(page, "url", "$.page")
        if url and not url.startswith(("https://", "http://")):
            c.must("$.page.url", "must be an absolute URL")
        c.time(page, "updated_at", "$.page")

    status = c.obj(data, "status", "$")
    indicator = None
    if status is not None:
        indicator = c.enum(status, "indicator", "$.status", INDICATORS)
        c.string(status, "description", "$.status")

    worst = 0
    components = data.get("components")
    if not isinstance(components, list):
        c.must("$.components", "required array")
        components = []
    ids: set[str] = set()
    groups: set[str] = set()
    for n, comp in enumerate(components):
        path = f"$.components[{n}]"
        if not isinstance(comp, dict):
            c.must(path, "must be an object")
            continue
        cid = c.string(comp, "id", path)
        if cid:
            if cid in ids:
                c.must(f"{path}.id", f"duplicate component id {cid!r}")
            ids.add(cid)
            if comp.get("group") is True:
                groups.add(cid)
        c.string(comp, "name", path)
        c.enum(comp, "status", path, COMPONENT_STATUSES)
        c.time(comp, "updated_at", path, "SHOULD")
        if "position" in comp and comp["position"] is not None and (not isinstance(comp["position"], int) or isinstance(comp["position"], bool)):
            c.must(f"{path}.position", "must be an integer")
        if "group" in comp and not isinstance(comp["group"], bool):
            c.must(f"{path}.group", "must be a boolean")
    for n, comp in enumerate(components):
        if isinstance(comp, dict) and comp.get("group_id") is not None and comp["group_id"] not in groups:
            c.must(f"$.components[{n}].group_id", f"refers to {comp['group_id']!r}, which is not a group in this document")

    incidents = data.get("incidents")
    if not isinstance(incidents, list):
        c.must("$.incidents", "required array")
        incidents = []
    for n, inc in enumerate(incidents):
        sev = _incident(c, inc, f"$.incidents[{n}]", INCIDENT_STATUSES, maintenance=False)
        worst = max(worst, sev)

    maint = data.get("scheduled_maintenances")
    if maint is None:
        c.should("$.scheduled_maintenances", "recommended array")
    elif not isinstance(maint, list):
        c.must("$.scheduled_maintenances", "must be an array")
    else:
        for n, m in enumerate(maint):
            _incident(c, m, f"$.scheduled_maintenances[{n}]", MAINTENANCE_STATUSES, maintenance=True)

    if indicator in INDICATORS and indicator_severity(indicator) < worst:
        c.should("$.status.indicator", f"{indicator!r} is less severe than an open incident (section 5)")
    return c.issues


def _incident(c: _Checker, inc: Any, path: str, statuses: tuple[str, ...], maintenance: bool) -> int:
    if not isinstance(inc, dict):
        c.must(path, "must be an object")
        return 0
    c.string(inc, "id", path)
    c.string(inc, "name", path)
    status = c.enum(inc, "status", path, statuses)
    impact = c.enum(inc, "impact", path, IMPACTS)
    c.time(inc, "created_at", path)
    c.time(inc, "updated_at", path, "SHOULD")
    c.time(inc, "resolved_at", path, "OPTIONAL")
    if maintenance:
        c.time(inc, "scheduled_for", path)
        c.time(inc, "scheduled_until", path)
        start, end = inc.get("scheduled_for"), inc.get("scheduled_until")
        if isinstance(start, str) and isinstance(end, str) and _valid_time(start) and _valid_time(end) and _parse(end) < _parse(start):
            c.must(f"{path}.scheduled_until", "is before scheduled_for")
    updates = inc.get("incident_updates")
    if updates is None:
        c.should(f"{path}.incident_updates", "recommended array")
    elif not isinstance(updates, list):
        c.must(f"{path}.incident_updates", "must be an array")
    else:
        times = []
        for n, u in enumerate(updates):
            upath = f"{path}.incident_updates[{n}]"
            if not isinstance(u, dict):
                c.must(upath, "must be an object")
                continue
            c.string(u, "id", upath)
            c.enum(u, "status", upath, statuses)
            if not isinstance(u.get("body"), str):
                c.must(f"{upath}.body", "required string")
            c.time(u, "created_at", upath)
            if isinstance(u.get("created_at"), str) and _valid_time(u["created_at"]):
                times.append(_parse(u["created_at"]))
        if times != sorted(times, reverse=True):
            c.should(f"{path}.incident_updates", "updates should be ordered newest first")
    if not isinstance(inc.get("components"), list):
        c.should(f"{path}.components", "recommended array of affected components")
    if maintenance or status in ("resolved", "postmortem") or impact is None:
        return 0
    return impact_severity(impact)


def _parse(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("z", "Z").replace("Z", "+00:00"))


def validate_http(resp: Response) -> list[Issue]:
    """Checks how a document is served (section 6)."""
    c = _Checker()
    if not resp.url.startswith("https://"):
        c.must("http", f"served over {resp.url.split(':', 1)[0].upper()}, not HTTPS")
    ctype = resp.headers.get("content-type", "")
    if ctype.split(";")[0].strip().lower() != "application/json":
        c.must("http.content-type", f"must be application/json, got {ctype or 'nothing'!r}")
    if resp.headers.get("access-control-allow-origin") != "*":
        c.should("http.access-control-allow-origin", "should be * so that browser dashboards can read the document")
    cache = resp.headers.get("cache-control", "")
    if "max-age" not in cache:
        c.should("http.cache-control", "should set max-age")
    if not resp.headers.get("etag") and not resp.headers.get("last-modified"):
        c.should("http.etag", "should send ETag or Last-Modified for conditional requests")
    return c.issues
