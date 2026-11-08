import unittest

from statusdoc import validate_document, validate_http
from statusdoc.fetch import Response
from tests.helpers import GOOD_HEADERS, fixture, incident, minimal


def messages(issues, level=None):
    return [f"{i.path}: {i.message}" for i in issues if level is None or i.level == level]


class ValidateDocumentTest(unittest.TestCase):
    def test_minimal_document_is_clean(self):
        self.assertEqual(messages(validate_document(minimal(incidents=[incident()], status={"indicator": "major", "description": "Partial outage"}))), [])

    def test_real_documents_have_no_errors(self):
        for name in ("github", "claude", "openai"):
            self.assertEqual(messages(validate_document(fixture(name)), "MUST"), [], name)

    def test_missing_and_mistyped_members(self):
        doc = minimal()
        del doc["page"]["name"]
        doc["page"]["updated_at"] = "yesterday"
        doc["status"] = {"indicator": "none"}
        doc["components"][1]["position"] = "first"
        del doc["incidents"]
        errors = messages(validate_document(doc), "MUST")
        self.assertIn("$.page.name: required string", errors)
        self.assertIn("$.page.updated_at: not an RFC 3339 timestamp: 'yesterday'", errors)
        self.assertIn("$.status.description: required string", errors)
        self.assertIn("$.components[1].position: must be an integer", errors)
        self.assertIn("$.incidents: required array", errors)

    def test_identity_and_references(self):
        comps = minimal()["components"]
        comps[2]["id"] = "api"
        comps[1]["group_id"] = "nope"
        errors = messages(validate_document(minimal(components=comps)), "MUST")
        self.assertIn("$.components[2].id: duplicate component id 'api'", errors)
        self.assertIn("$.components[1].group_id: refers to 'nope', which is not a group in this document", errors)

    def test_recommendations(self):
        inc = incident(impact="critical")
        inc["incident_updates"].reverse()
        doc = minimal(incidents=[inc])
        del doc["osd_version"]
        warnings = messages(validate_document(doc), "SHOULD")
        self.assertIn('$.osd_version: recommended: "0.1"', warnings)
        self.assertIn("$.incidents[0].incident_updates: updates should be ordered newest first", warnings)
        self.assertIn("$.status.indicator: 'none' is less severe than an open incident (section 5)", warnings)

    def test_unknown_enumerations_are_warnings(self):
        comps = minimal()["components"]
        comps[1]["status"] = "on_fire"
        issues = validate_document(minimal(components=comps))
        self.assertEqual(messages(issues, "MUST"), [])
        self.assertTrue(any("on_fire" in m for m in messages(issues, "SHOULD")))

    def test_maintenance_window(self):
        m = incident(status="scheduled", impact="none", scheduled_for="2026-11-08T12:00:00Z", scheduled_until="2026-11-08T11:00:00Z")
        self.assertIn(
            "$.scheduled_maintenances[0].scheduled_until: is before scheduled_for", messages(validate_document(minimal(scheduled_maintenances=[m])), "MUST")
        )
        del m["scheduled_for"]
        self.assertIn("$.scheduled_maintenances[0].scheduled_for: required string", messages(validate_document(minimal(scheduled_maintenances=[m])), "MUST"))
        # An unknown end is allowed (null), but recommended.
        m = incident(status="scheduled", impact="none", scheduled_for="2026-11-08T12:00:00Z", scheduled_until=None)
        self.assertEqual(messages(validate_document(minimal(scheduled_maintenances=[m])), "MUST"), [])
        del m["scheduled_until"]
        self.assertIn("$.scheduled_maintenances[0].scheduled_until: recommended", messages(validate_document(minimal(scheduled_maintenances=[m])), "SHOULD"))


class ValidateHTTPTest(unittest.TestCase):
    def test_good_headers(self):
        self.assertEqual(validate_http(Response("https://s.example.com/x.json", 200, dict(GOOD_HEADERS))), [])

    def test_bad_headers(self):
        issues = validate_http(Response("http://s.example.com/x.json", 200, {"content-type": "text/html"}))
        self.assertEqual(
            messages(issues),
            [
                "http: served over HTTP, not HTTPS",
                "http.content-type: must be application/json, got 'text/html'",
                "http.access-control-allow-origin: should be * so that browser dashboards can read the document",
                "http.cache-control: should set max-age",
                "http.etag: should send ETag or Last-Modified for conditional requests",
            ],
        )


if __name__ == "__main__":
    unittest.main()
