import gzip
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from statusdoc import DiscoveryError, discover
from statusdoc.discover import load_registry
from statusdoc.fetch import FetchError, get
from tests.helpers import FakeWeb, minimal, unreachable

REG = {"acme.com": {"page": "https://status.acme-cdn.net", "document": "https://status.acme-cdn.net/api/v2/summary.json"}}


class DiscoverTest(unittest.TestCase):
    def test_well_known_discovery_document(self):
        web = FakeWeb(
            {
                "https://acme.com/.well-known/status": {"osd_version": "0.1", "document": "https://elsewhere.io/s.json", "page": "https://elsewhere.io"},
                "https://elsewhere.io/s.json": minimal(),
            }
        )
        d = discover("acme.com", fetch=web, registry=REG)
        self.assertEqual((d.method, d.document_url, d.page_url), ("well-known", "https://elsewhere.io/s.json", "https://elsewhere.io"))
        self.assertEqual(d.document.name, "Example")

    def test_well_known_serving_the_document(self):
        web = FakeWeb({"https://acme.com/.well-known/status": minimal()})
        d = discover("www.ACME.com.", fetch=web, registry={})
        self.assertEqual(d.method, "well-known")

    def test_well_known_wins_over_registry(self):
        web = FakeWeb({"https://acme.com/.well-known/status": minimal(), "https://status.acme-cdn.net/api/v2/summary.json": minimal()})
        self.assertEqual(discover("acme.com", fetch=web, registry=REG).method, "well-known")

    def test_registry_for_domain_and_subdomains(self):
        web = FakeWeb({"https://status.acme-cdn.net/api/v2/summary.json": minimal()})
        self.assertEqual(discover("acme.com", fetch=web, registry=REG).method, "registry")
        self.assertEqual(discover("api.eu.acme.com", fetch=web, registry=REG).method, "registry")

    def test_conventions(self):
        web = FakeWeb({"https://www.initechstatus.com/api/v2/summary.json": minimal()})
        d = discover("initech.io", fetch=web, registry={})
        self.assertEqual((d.method, d.page_url), ("convention", "https://www.initechstatus.com"))
        self.assertIn("https://status.initech.io/api/v2/summary.json", web.requests)

    def test_better_stack_convention(self):
        from tests.helpers import fixture

        web = FakeWeb({"https://status.globex.com/index.json": fixture("betterstack")})
        self.assertEqual(discover("globex.com", fetch=web, registry={}).document.source_format, "betterstack")

    def test_urls(self):
        web = FakeWeb({"https://status.x.com/api/v2/summary.json": minimal()})
        self.assertEqual(discover("https://status.x.com/api/v2/summary.json", fetch=web).method, "url")
        d = discover("https://status.x.com/", fetch=web)
        self.assertEqual((d.method, d.document_url), ("convention", "https://status.x.com/api/v2/summary.json"))

    def test_failure_lists_attempts(self):
        web = FakeWeb(
            {
                "https://nope.dev/.well-known/status": unreachable("https://nope.dev/.well-known/status"),
                "https://status.nope.dev/api/v2/summary.json": {"not": "status"},
            }
        )
        with self.assertRaises(DiscoveryError) as ctx:
            discover("nope.dev", fetch=web, registry={})
        reasons = dict(ctx.exception.attempts)
        self.assertEqual(reasons["https://nope.dev/.well-known/status"], "connection refused")
        self.assertEqual(reasons["https://status.nope.dev/api/v2/summary.json"], "JSON, but not a status document")
        self.assertEqual(reasons["https://status.nope.dev/index.json"], "HTTP 404")

    def test_invalid_target(self):
        with self.assertRaises(ValueError):
            discover("not a domain", fetch=FakeWeb({}))

    def test_bundled_registry(self):
        reg = load_registry()
        self.assertGreaterEqual(len(reg), 30)
        self.assertEqual(reg["github.com"]["document"], "https://www.githubstatus.com/api/v2/summary.json")
        self.assertTrue(all(v["document"].startswith("https://") for v in reg.values()))


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/doc":
            body = json.dumps(minimal()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body)
                self.send_header("Content-Encoding", "gzip")
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/doc")
            body = b""
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            body = b""
        elif self.path == "/huge":
            self.send_response(200)
            body = b"x" * (10 * 1024 * 1024 + 10)
        else:
            self.send_response(404)
            body = b"no"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_decodes_gzip_and_follows_redirects(self):
        r = get(self.base + "/redirect")
        self.assertEqual((r.status, r.url), (200, self.base + "/doc"))
        self.assertEqual(r.json()["page"]["name"], "Example")
        self.assertEqual(r.headers["content-type"], "application/json")

    def test_get_returns_error_statuses(self):
        self.assertEqual(get(self.base + "/missing").status, 404)

    def test_limits(self):
        with self.assertRaises(FetchError):
            get(self.base + "/huge")
        r = get(self.base + "/loop")
        self.assertEqual(r.status, 302)  # gave up after the redirect limit

    def test_unreachable(self):
        with self.assertRaises(FetchError):
            get("http://127.0.0.1:1/doc", timeout=2)

    def test_discover_over_real_http(self):
        host = self.base.removeprefix("http://")
        d = discover(f"http://{host}/doc")
        self.assertEqual(d.document.name, "Example")


if __name__ == "__main__":
    unittest.main()
