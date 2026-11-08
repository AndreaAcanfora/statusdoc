import unittest

from statusdoc import detect, from_betterstack, load, validate_document
from tests.helpers import fixture


def betterstack(resources, reports=(), updates=()):
    return {
        "data": {
            "id": "1",
            "type": "status_page",
            "attributes": {"company_name": "Acme", "custom_domain": "status.acme.dev", "updated_at": "2026-11-08T10:00:00Z"},
        },
        "included": [
            {"id": "10", "type": "status_page_section", "attributes": {"name": "Core", "position": 0}},
            *[
                {"id": rid, "type": "status_page_resource", "attributes": {"status_page_section_id": 10, "public_name": name, "status": st, "position": i}}
                for i, (rid, name, st) in enumerate(resources)
            ],
            *reports,
            *updates,
        ],
    }


class BetterStackTest(unittest.TestCase):
    def test_real_page(self):
        data = fixture("betterstack")
        self.assertEqual(detect(data), "betterstack")
        doc = load(data)
        self.assertEqual(doc.source_format, "betterstack")
        self.assertEqual(doc.name, "Better Stack")
        self.assertEqual(doc.url, "https://status.betterstack.com")
        # "not_monitored" resources are left out rather than counted as degraded.
        self.assertNotIn("Uptime backend processing health", [c.name for c in doc.components])
        self.assertEqual(doc.level, "operational")
        self.assertEqual([i for i in validate_document(doc.to_dict()) if i.level == "MUST"], [])

    def test_outage_becomes_an_incident(self):
        report = {
            "id": "r1",
            "type": "status_report",
            "attributes": {
                "title": "API down",
                "report_type": "manual",
                "starts_at": "2026-11-08T09:00:00Z",
                "ends_at": None,
                "aggregate_state": "downtime",
                "affected_resources": [{"status_page_resource_id": "2", "status": "downtime"}],
            },
            "relationships": {"status_updates": {"data": [{"id": "u1", "type": "status_update"}, {"id": "u2", "type": "status_update"}]}},
        }
        updates = [
            {"id": "u1", "type": "status_update", "attributes": {"message": "Investigating", "published_at": "2026-11-08T09:01:00Z"}},
            {"id": "u2", "type": "status_update", "attributes": {"message": "Fix deployed", "published_at": "2026-11-08T09:20:00Z"}},
        ]
        data = betterstack([("1", "Web", "operational"), ("2", "API", "downtime")], [report], updates)
        data["data"]["attributes"]["aggregate_state"] = "downtime"
        doc = from_betterstack(data)
        self.assertEqual(doc.indicator, "critical")
        self.assertEqual(doc.level, "critical")
        group = next(c for c in doc.components if c.group)
        self.assertEqual(group.status, "major_outage")
        [inc] = doc.open_incidents
        self.assertEqual((inc.name, inc.impact, inc.status), ("API down", "critical", "investigating"))
        self.assertEqual([u.body for u in inc.updates], ["Fix deployed", "Investigating"])
        self.assertEqual([c.name for c in inc.components], ["API"])

    def test_maintenance_report(self):
        report = {
            "id": "r2",
            "type": "status_report",
            "attributes": {
                "title": "DB upgrade",
                "report_type": "maintenance",
                "starts_at": "2026-11-08T09:00:00Z",
                "ends_at": None,
                "aggregate_state": "maintenance",
                "affected_resources": [{"status_page_resource_id": "1", "status": "maintenance"}],
            },
        }
        doc = from_betterstack(betterstack([("1", "DB", "maintenance")], [report]))
        self.assertEqual(doc.level, "maintenance")
        self.assertEqual([m.name for m in doc.active_maintenances], ["DB upgrade"])
        self.assertEqual(doc.incidents, [])


if __name__ == "__main__":
    unittest.main()


class SlackTest(unittest.TestCase):
    def test_all_clear(self):
        data = fixture("slack")
        self.assertEqual(detect(data), "slack")
        doc = load(data)
        self.assertEqual((doc.name, doc.level, doc.source_format), ("Slack", "operational", "slack"))
        self.assertIn("Huddles", [c.name for c in doc.components])
        self.assertEqual([i for i in validate_document(doc.to_dict()) if i.level == "MUST"], [])

    def test_issues_from_the_documented_example(self):
        # Shaped like the sample response in Slack's Status API documentation.
        data = {
            "status": "active",
            "date_created": "2019-04-09T07:35:46-07:00",
            "date_updated": "2019-04-09T07:35:46-07:00",
            "active_incidents": [
                {
                    "id": "546",
                    "date_created": "2018-09-07T14:35:00-07:00",
                    "date_updated": "2018-09-07T18:34:15-07:00",
                    "title": "Slack's forwarding email feature is failing for some customers",
                    "type": "incident",
                    "status": "active",
                    "url": "https://slack-status.com/2018-09/7dea1cd14cd0f657",
                    "services": ["Apps/Integrations/APIs"],
                    "notes": [
                        {"date_created": "2018-09-07T15:00:00-07:00", "body": "Investigating."},
                        {"date_created": "2018-09-07T18:34:15-07:00", "body": "Technical Summary: fixed."},
                    ],
                },
                {
                    "id": "547",
                    "date_created": "2018-09-07T14:00:00-07:00",
                    "title": "Messages not sending",
                    "type": "outage",
                    "status": "active",
                    "services": ["Messaging"],
                    "notes": [],
                },
                {
                    "id": "548",
                    "date_created": "2018-09-08T09:00:00-07:00",
                    "title": "Database upgrade",
                    "type": "notice",
                    "status": "scheduled",
                    "services": [],
                    "notes": [],
                },
                {
                    "id": "549",
                    "date_created": "2018-09-06T09:00:00-07:00",
                    "title": "Old issue",
                    "type": "incident",
                    "status": "resolved",
                    "services": ["Search"],
                    "notes": [],
                },
            ],
        }
        doc = load(data)
        self.assertEqual(doc.level, "major")
        status = {c.name: c.status for c in doc.components}
        self.assertEqual(status["Messaging"], "major_outage")
        self.assertEqual(status["Apps/Integrations/APIs"], "degraded_performance")
        self.assertEqual(status["Search"], "operational")
        self.assertEqual(
            [(i.name, i.impact) for i in doc.open_incidents],
            [("Slack's forwarding email feature is failing for some customers", "minor"), ("Messages not sending", "major")],
        )
        self.assertEqual(doc.open_incidents[0].updates[0].body, "Technical Summary: fixed.")
        self.assertEqual([m.name for m in doc.maintenances], ["Database upgrade"])
        self.assertEqual([i for i in validate_document(doc.to_dict()) if i.level == "MUST"], [])
