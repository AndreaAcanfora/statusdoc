"""Data model of an Open Status Document (SPEC.md, section 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OSD_VERSION = "0.1"

INDICATORS = ("none", "maintenance", "minor", "major", "critical")
COMPONENT_STATUSES = ("operational", "under_maintenance", "degraded_performance", "partial_outage", "major_outage")
IMPACTS = ("none", "minor", "major", "critical")
INCIDENT_STATUSES = ("investigating", "identified", "monitoring", "resolved", "postmortem")
MAINTENANCE_STATUSES = ("scheduled", "in_progress", "verifying", "completed")

# Severity scale of section 5: 0 (fine) to 4 (critical).
LEVELS = ("operational", "maintenance", "minor", "major", "critical")
_INDICATOR_SEVERITY = {v: i for i, v in enumerate(INDICATORS)}
_COMPONENT_SEVERITY = {v: i for i, v in enumerate(COMPONENT_STATUSES)}
_IMPACT_SEVERITY = {"none": 0, "minor": 2, "major": 3, "critical": 4}
_RESOLVED = ("resolved", "postmortem", "completed")


def indicator_severity(value: str) -> int:
    # Section 4.7: an unknown indicator counts as minor.
    return _INDICATOR_SEVERITY.get(value, 2)


def component_severity(value: str) -> int:
    # Section 4.7: an unknown component status counts as degraded_performance.
    return _COMPONENT_SEVERITY.get(value, 2)


def impact_severity(value: str) -> int:
    # Section 4.7: an unknown impact counts as minor.
    return _IMPACT_SEVERITY.get(value, 2)


@dataclass
class Component:
    id: str
    name: str
    status: str
    description: str | None = None
    group: bool = False
    group_id: str | None = None
    position: int | None = None
    updated_at: str | None = None

    @property
    def severity(self) -> int:
        return component_severity(self.status)


@dataclass
class Update:
    id: str
    status: str
    body: str
    created_at: str


@dataclass
class Incident:
    id: str
    name: str
    status: str
    impact: str
    created_at: str
    updated_at: str | None = None
    shortlink: str | None = None
    updates: list[Update] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    scheduled_for: str | None = None
    scheduled_until: str | None = None

    @property
    def resolved(self) -> bool:
        return self.status in _RESOLVED


@dataclass
class Document:
    name: str
    url: str
    updated_at: str
    indicator: str
    description: str
    components: list[Component] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    maintenances: list[Incident] = field(default_factory=list)
    osd_version: str | None = None
    #: Format the document was read from: "osd" or the name of an adapter.
    source_format: str = "osd"

    @property
    def open_incidents(self) -> list[Incident]:
        return [i for i in self.incidents if not i.resolved]

    @property
    def active_maintenances(self) -> list[Incident]:
        return [m for m in self.maintenances if m.status in ("in_progress", "verifying")]

    @property
    def severity(self) -> int:
        """Overall level (section 5): the indicator, raised by open incidents and active maintenance.

        Component statuses do not count: one location down out of hundreds
        does not make the whole service critical.
        """
        values = [indicator_severity(self.indicator)]
        values += [impact_severity(i.impact) for i in self.open_incidents]
        if self.active_maintenances:
            values.append(1)
        return max(values)

    @property
    def level(self) -> str:
        return LEVELS[self.severity]

    def to_dict(self) -> dict[str, Any]:
        """Returns the document in OSD form."""
        return {
            "osd_version": OSD_VERSION,
            "page": {"name": self.name, "url": self.url, "updated_at": self.updated_at},
            "status": {"indicator": self.indicator, "description": self.description},
            "components": [_component_dict(c) for c in self.components],
            "incidents": [_incident_dict(i) for i in self.incidents],
            "scheduled_maintenances": [_incident_dict(m) for m in self.maintenances],
        }


def _component_dict(c: Component) -> dict[str, Any]:
    d: dict[str, Any] = {"id": c.id, "name": c.name, "status": c.status}
    for key in ("description", "group_id", "position", "updated_at"):
        if getattr(c, key) is not None:
            d[key] = getattr(c, key)
    if c.group:
        d["group"] = True
    return d


def _incident_dict(i: Incident) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": i.id,
        "name": i.name,
        "status": i.status,
        "impact": i.impact,
        "created_at": i.created_at,
        "incident_updates": [{"id": u.id, "status": u.status, "body": u.body, "created_at": u.created_at} for u in i.updates],
        "components": [_component_dict(c) for c in i.components],
    }
    for key in ("updated_at", "shortlink", "scheduled_for", "scheduled_until"):
        if getattr(i, key) is not None:
            d[key] = getattr(i, key)
    return d


class FormatError(ValueError):
    """The data is not a status document."""


def parse(data: Any) -> Document:
    """Parses an OSD (or Statuspage-shaped) document leniently, as section 4.7 asks.

    Raises FormatError when required structure is missing. Use
    statusdoc.validate for a strict check.
    """
    if not isinstance(data, dict):
        raise FormatError("a status document is a JSON object")
    page = data.get("page")
    status = data.get("status")
    if not isinstance(page, dict) or not isinstance(status, dict) or not isinstance(data.get("components"), list):
        raise FormatError("missing page, status or components")
    return Document(
        name=_str(page.get("name")),
        url=_str(page.get("url")),
        updated_at=_str(page.get("updated_at")),
        indicator=_str(status.get("indicator")) or "none",
        description=_str(status.get("description")),
        components=[_component(c) for c in data["components"] if isinstance(c, dict)],
        incidents=[_incident(i) for i in _list(data.get("incidents"))],
        maintenances=[_incident(m) for m in _list(data.get("scheduled_maintenances"))],
        osd_version=data.get("osd_version") if isinstance(data.get("osd_version"), str) else None,
    )


def _str(v: Any) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _opt(v: Any) -> str | None:
    return None if v is None else _str(v)


def _list(v: Any) -> list[dict[str, Any]]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _component(c: dict[str, Any]) -> Component:
    position = c.get("position")
    return Component(
        id=_str(c.get("id")),
        name=_str(c.get("name")),
        status=_str(c.get("status")),
        description=_opt(c.get("description")),
        group=c.get("group") is True,
        group_id=_opt(c.get("group_id")),
        position=position if isinstance(position, int) and not isinstance(position, bool) else None,
        updated_at=_opt(c.get("updated_at")),
    )


def _incident(i: dict[str, Any]) -> Incident:
    return Incident(
        id=_str(i.get("id")),
        name=_str(i.get("name")),
        status=_str(i.get("status")),
        impact=_str(i.get("impact")) or "none",
        created_at=_str(i.get("created_at")),
        updated_at=_opt(i.get("updated_at")),
        shortlink=_opt(i.get("shortlink")),
        updates=[
            Update(id=_str(u.get("id")), status=_str(u.get("status")), body=_str(u.get("body")), created_at=_str(u.get("created_at")))
            for u in _list(i.get("incident_updates"))
        ],
        components=[_component(c) for c in _list(i.get("components"))],
        scheduled_for=_opt(i.get("scheduled_for")),
        scheduled_until=_opt(i.get("scheduled_until")),
    )
