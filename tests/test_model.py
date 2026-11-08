import unittest

from statusdoc import FormatError, load, parse, validate_document
from tests.helpers import fixture, incident, minimal


class ModelTest(unittest.TestCase):
    def test_real_documents(self):
        gh = parse(fixture("github"))
        self.assertEqual(gh.name, "GitHub")
        self.assertEqual(gh.level, "operational")
        self.assertTrue(all(c.id and c.name for c in gh.components))

        claude = parse(fixture("claude"))
        self.assertEqual(claude.indicator, "minor")
        self.assertEqual(claude.level, "minor")
        self.assertEqual(len(claude.open_incidents), 1)
        self.assertTrue(claude.open_incidents[0].updates)

    def test_level_is_the_indicator_raised_by_open_incidents(self):
        doc = parse(minimal(incidents=[incident(impact="critical")]))
        self.assertEqual(doc.level, "critical")
        resolved = parse(minimal(incidents=[incident(status="resolved")]))
        self.assertEqual(resolved.level, "operational")
        self.assertEqual(parse(minimal(status={"indicator": "major", "description": "x"})).level, "major")

    def test_component_outages_do_not_set_the_level(self):
        # One location down out of hundreds: the publisher's indicator decides.
        comps = minimal()["components"]
        comps[1]["status"] = "major_outage"
        doc = parse(minimal(components=comps, status={"indicator": "minor", "description": "Partially Degraded Service"}))
        self.assertEqual(doc.level, "minor")

    def test_active_maintenance(self):
        m = incident(status="in_progress", impact="none", scheduled_for="2026-11-08T09:00:00Z", scheduled_until="2026-11-08T11:00:00Z")
        doc = parse(minimal(scheduled_maintenances=[m]))
        self.assertEqual(doc.level, "maintenance")
        planned = parse(minimal(scheduled_maintenances=[dict(m, status="scheduled")]))
        self.assertEqual(planned.level, "operational")

    def test_unknown_values_are_tolerated(self):
        comps = minimal()["components"]
        comps[1]["status"] = "on_fire"
        doc = parse(minimal(components=comps, status={"indicator": "weird", "description": "?"}, incidents=[incident(impact="huge", status="new")]))
        # Section 4.7: unknown indicator or impact → minor, unknown status → degraded, unknown incident status → unresolved.
        self.assertEqual(doc.severity, 2)
        self.assertEqual(doc.components[1].severity, 2)
        self.assertEqual(len(doc.open_incidents), 1)

    def test_rejects_non_documents(self):
        for bad in ([], {}, {"page": {}, "status": {}}, {"page": 1, "status": {}, "components": []}):
            with self.assertRaises(FormatError):
                parse(bad)
        with self.assertRaises(FormatError):
            load({"hello": "world"})

    def test_to_dict_round_trips_and_validates(self):
        doc = parse(minimal(incidents=[incident()]))
        again = parse(doc.to_dict())
        self.assertEqual(again, doc)
        self.assertEqual([i for i in validate_document(doc.to_dict()) if i.level == "MUST"], [])


if __name__ == "__main__":
    unittest.main()
