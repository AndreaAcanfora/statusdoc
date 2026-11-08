"""Readers for status formats that are not OSD yet."""

from __future__ import annotations

from typing import Any

from .model import Component, Document, FormatError, Incident, Update, parse

# Better Stack resource states → OSD component statuses.
_BETTERSTACK_STATUS = {
    "operational": "operational",
    "maintenance": "under_maintenance",
    "degraded": "degraded_performance",
    "downtime": "major_outage",
}
_BETTERSTACK_SEVERITY = {"operational": 0, "under_maintenance": 1, "degraded_performance": 2, "partial_outage": 3, "major_outage": 4}
_IMPACT_OF = {"degraded_performance": "minor", "partial_outage": "major", "major_outage": "critical"}
_INDICATOR_OF = {0: "none", 1: "maintenance", 2: "minor", 3: "major", 4: "critical"}
_DESCRIPTION_OF = {
    0: "All Systems Operational",
    1: "Service Under Maintenance",
    2: "Partially Degraded Service",
    3: "Partial System Outage",
    4: "Major System Outage",
}


def detect(data: Any) -> str | None:
    """Returns the format of a parsed JSON document, or None if unknown."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("page"), dict) and isinstance(data.get("status"), dict) and isinstance(data.get("components"), list):
        return "osd"
    d = data.get("data")
    if isinstance(d, dict) and d.get("type") == "status_page" and isinstance(data.get("included"), list):
        return "betterstack"
    if isinstance(data.get("status"), str) and isinstance(data.get("active_incidents"), list):
        return "slack"
    return None


def load(data: Any) -> Document:
    """Reads a status document in any supported format."""
    fmt = detect(data)
    if fmt == "osd":
        return parse(data)
    if fmt == "betterstack":
        return from_betterstack(data)
    if fmt == "slack":
        return from_slack(data)
    raise FormatError("not a status document in a known format")


def from_betterstack(data: dict[str, Any]) -> Document:
    """Converts a Better Stack status page (`/index.json`, JSON:API) to OSD."""
    page = data["data"].get("attributes", {})
    included = [x for x in data["included"] if isinstance(x, dict)]

    def of_type(t: str) -> list[dict[str, Any]]:
        return [x for x in included if x.get("type") == t]

    components: dict[str, Component] = {}
    sections = {str(s.get("id")): s.get("attributes", {}) for s in of_type("status_page_section")}
    for s_id, s in sections.items():
        components["section-" + s_id] = Component(
            id="section-" + s_id, name=str(s.get("name", "")).strip(), status="operational", group=True, position=s.get("position")
        )
    for r in of_type("status_page_resource"):
        a = r.get("attributes", {})
        if a.get("status") == "not_monitored":
            # No data, so no claim either way: leave it out.
            continue
        section = a.get("status_page_section_id")
        c = Component(
            id=str(r.get("id")),
            name=str(a.get("public_name", "")),
            status=_BETTERSTACK_STATUS.get(str(a.get("status")), "degraded_performance"),
            description=a.get("explanation") or None,
            group_id=f"section-{section}" if section is not None and str(section) in sections else None,
            position=a.get("position"),
        )
        components[c.id] = c
    # A section is as bad as its worst resource.
    for c in components.values():
        if c.group_id:
            group = components[c.group_id]
            if _BETTERSTACK_SEVERITY[c.status] > _BETTERSTACK_SEVERITY[group.status]:
                group.status = c.status

    updates = {str(u.get("id")): u.get("attributes", {}) for u in of_type("status_update")}
    incidents: list[Incident] = []
    maintenances: list[Incident] = []
    for report in of_type("status_report"):
        a = report.get("attributes", {})
        resolved = a.get("aggregate_state") == "resolved" or a.get("ends_at") is not None
        affected = [
            components[str(x.get("status_page_resource_id"))] for x in a.get("affected_resources", []) if str(x.get("status_page_resource_id")) in components
        ]
        worst = max((_BETTERSTACK_SEVERITY[c.status] for c in affected), default=0)
        rel = report.get("relationships", {}).get("status_updates", {}).get("data", [])
        report_updates = [updates[str(x.get("id"))] for x in rel if str(x.get("id")) in updates]
        report_updates.sort(key=lambda u: str(u.get("published_at", "")), reverse=True)
        is_maintenance = a.get("report_type") == "maintenance"
        item = Incident(
            id=str(report.get("id")),
            name=str(a.get("title", "")),
            status=("completed" if resolved else "in_progress") if is_maintenance else ("resolved" if resolved else "investigating"),
            impact="none" if is_maintenance else _IMPACT_OF.get(_status_of(worst), "minor"),
            created_at=str(a.get("starts_at", "")),
            updates=[
                Update(id=str(i), status="resolved" if resolved else "investigating", body=str(u.get("message", "")), created_at=str(u.get("published_at", "")))
                for i, u in enumerate(report_updates)
            ],
            components=affected,
            scheduled_for=a.get("starts_at") if is_maintenance else None,
            scheduled_until=a.get("ends_at") if is_maintenance else None,
        )
        if is_maintenance:
            if not resolved:
                maintenances.append(item)
        elif not resolved:
            incidents.append(item)

    # The page's own aggregate state is the publisher's judgement (spec section 4.3);
    # fall back to the worst resource when it is missing.
    aggregate = _BETTERSTACK_STATUS.get(str(page.get("aggregate_state")))
    worst = _BETTERSTACK_SEVERITY[aggregate] if aggregate else max((_BETTERSTACK_SEVERITY[c.status] for c in components.values() if not c.group), default=0)
    domain = page.get("custom_domain") or f"{page.get('subdomain', '')}.betteruptime.com"
    return Document(
        name=str(page.get("company_name", "")),
        url=f"https://{domain}",
        updated_at=str(page.get("updated_at", "")),
        indicator=_INDICATOR_OF[worst],
        description=_DESCRIPTION_OF[worst],
        components=sorted(components.values(), key=lambda c: (c.group_id or c.id, not c.group, c.position or 0)),
        incidents=incidents,
        maintenances=maintenances,
        source_format="betterstack",
    )


def _status_of(severity: int) -> str:
    for status, s in _BETTERSTACK_SEVERITY.items():
        if s == severity:
            return status
    return "operational"


# Services listed by the Slack Status API documentation for /api/v2.0.0/current.
SLACK_SERVICES = (
    "Login/SSO",
    "Messaging",
    "Notifications",
    "Search",
    "Workspace/Org Administration",
    "Canvases",
    "Connectivity",
    "Files",
    "Huddles",
    "Apps/Integrations/APIs",
    "Workflows",
)
# Slack issue types → (OSD incident impact, status of the affected services).
_SLACK_TYPES = {"outage": ("major", "major_outage"), "incident": ("minor", "degraded_performance"), "notice": ("none", "operational")}


def from_slack(data: dict[str, Any]) -> Document:
    """Converts the Slack Status API (`https://slack-status.com/api/v2.0.0/current`) to OSD.

    Slack reports issues, not component states: affected services take the
    status implied by the issue type (an outage makes them major_outage, an
    incident degraded_performance, a notice leaves them operational).
    """
    services: dict[str, Component] = {}

    def service(name: str) -> Component:
        if name not in services:
            slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
            services[name] = Component(id=slug, name=name, status="operational", position=len(services))
        return services[name]

    for name in SLACK_SERVICES:
        service(name)

    incidents: list[Incident] = []
    maintenances: list[Incident] = []
    worst = 0
    for item in data.get("active_incidents", []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", ""))
        kind = str(item.get("type", ""))
        impact, service_status = _SLACK_TYPES.get(kind, ("minor", "degraded_performance"))
        notes = [n for n in item.get("notes", []) if isinstance(n, dict)]
        notes.sort(key=lambda n: str(n.get("date_created", "")), reverse=True)
        affected = [service(str(s)) for s in item.get("services", []) if isinstance(s, str)]
        entry = Incident(
            id=str(item.get("id", "")),
            name=str(item.get("title", "")),
            status="",
            impact=impact,
            created_at=str(item.get("date_created", "")),
            updated_at=item.get("date_updated"),
            shortlink=item.get("url"),
            updates=[
                Update(id=f"{item.get('id', '')}-{n}", status="", body=str(note.get("body", "")), created_at=str(note.get("date_created", "")))
                for n, note in enumerate(notes)
            ],
        )
        if status in ("scheduled", "completed", "cancelled"):
            if status == "scheduled":
                entry.status, entry.impact = "scheduled", "none"
                entry.scheduled_for = entry.created_at
                maintenances.append(entry)
            continue
        entry.status = "resolved" if status == "resolved" else "investigating"
        for u in entry.updates:
            u.status = entry.status
        if not entry.resolved:
            for c in affected:
                if _BETTERSTACK_SEVERITY[service_status] > _BETTERSTACK_SEVERITY[c.status]:
                    c.status = service_status
            worst = max(worst, {"none": 0, "minor": 2, "major": 3}[impact])
        entry.components = [Component(id=c.id, name=c.name, status=c.status) for c in affected]
        incidents.append(entry)

    return Document(
        name="Slack",
        url="https://slack-status.com",
        updated_at=str(data.get("date_updated", "")),
        indicator=_INDICATOR_OF[worst],
        description=_DESCRIPTION_OF[worst],
        components=list(services.values()),
        incidents=incidents,
        maintenances=maintenances,
        source_format="slack",
    )
