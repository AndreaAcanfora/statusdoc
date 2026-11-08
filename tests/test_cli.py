import io
import json
import unittest

from statusdoc.cli import EXIT_DEGRADED, EXIT_OK, EXIT_UNREACHABLE, main
from tests.helpers import FakeWeb, fixture, incident, minimal

WEB = {
    "https://ok.com/.well-known/status": minimal(),
    "https://slow.com/.well-known/status": minimal(status={"indicator": "minor", "description": "Degraded"}, incidents=[incident(impact="minor")]),
    "https://down.com/.well-known/status": minimal(status={"indicator": "critical", "description": "Down"}, incidents=[incident(impact="critical")]),
    "https://bs.com/.well-known/status": fixture("betterstack"),
}


def run(*argv):
    out = io.StringIO()
    code = main(list(argv), out=out, fetch=FakeWeb(WEB), registry={})
    return code, out.getvalue()


class CLITest(unittest.TestCase):
    def test_check_text(self):
        code, out = run("check", "ok.com", "slow.com")
        self.assertEqual(code, EXIT_DEGRADED)
        self.assertIn("✓ ok.com    operational All Systems Operational", out)
        self.assertIn("! slow.com  minor       Degraded", out)
        self.assertIn("• Elevated errors (minor, investigating)", out)

    def test_check_thresholds(self):
        self.assertEqual(run("check", "ok.com")[0], EXIT_OK)
        self.assertEqual(run("check", "slow.com", "--fail-on", "major")[0], EXIT_OK)
        self.assertEqual(run("check", "down.com", "--fail-on", "critical")[0], EXIT_DEGRADED)
        self.assertEqual(run("check", "down.com", "--fail-on", "never")[0], EXIT_OK)

    def test_check_unreachable(self):
        code, out = run("check", "ok.com", "missing.example")
        self.assertEqual(code, EXIT_UNREACHABLE)
        self.assertIn("? missing.example  unreachable:", out)

    def test_check_json(self):
        _code, out = run("check", "--json", "-v", "down.com", "ok.com")
        data = json.loads(out)
        self.assertEqual([d["level"] for d in data], ["critical", "operational"])
        self.assertEqual(data[0]["incidents"][0]["impact"], "critical")
        self.assertEqual(data[0]["discovered_via"], "well-known")

    def test_discover(self):
        code, out = run("discover", "ok.com", "bs.com")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("ok.com: https://ok.com/.well-known/status (via well-known, osd)", out)
        self.assertIn("(via well-known, betterstack)", out)

    def test_validate(self):
        code, out = run("validate", "ok.com")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("conforming to OSD 0.1: 0 errors, 0 recommendations", out)
        code, out = run("validate", "https://ok.com/.well-known/status")
        self.assertEqual(code, EXIT_OK)
        code, out = run("validate", "bs.com")
        self.assertEqual(code, EXIT_DEGRADED)
        self.assertIn("betterstack format, not OSD", out)

    def test_convert(self):
        code, out = run("convert", "bs.com")
        self.assertEqual(code, EXIT_OK)
        doc = json.loads(out)
        self.assertEqual(doc["osd_version"], "0.1")
        self.assertEqual(doc["page"]["name"], "Better Stack")


if __name__ == "__main__":
    unittest.main()
