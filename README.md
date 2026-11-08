# statusdoc: Open Status Document

[![CI](https://github.com/AndreaAcanfora/statusdoc/actions/workflows/ci.yml/badge.svg)](https://github.com/AndreaAcanfora/statusdoc/actions/workflows/ci.yml)

A specification and a Python tool to **find, read and validate the status
pages of the services you depend on**, starting from nothing but their
domain.

```console
$ statusdoc check github.com anthropic.com cloudflare.com stripe.com
✓ github.com      operational All Systems Operational
! anthropic.com   minor       Partially Degraded Service
                  • Degraded performance for Claude Fable 5.1 (minor, investigating)
✗ cloudflare.com  major       Partial System Outage
                  • Spectrum Availability Issue in Phoenix (minor, monitoring)
◷ stripe.com      maintenance All Systems Operational
                  ◷ Scheduled maintenance for TWINT (until 2026-11-08T15:00:00.000Z)
```

- **Specification:** [SPEC.md](SPEC.md), Open Status Document (OSD) 0.1, draft.
- **Compatible with what is deployed:** OSD specifies the `summary.json`
  shape that Atlassian Statuspage made common and other providers mirror, so
  thousands of status pages already serve conforming documents.
- **Adds discovery:** `https://{domain}/.well-known/status` tells programs
  where a service's status document lives.
- **Zero dependencies**, Python 3.10+.

## Why

Status pages are for people. Programs need the same information: a CI
pipeline that should hold a deploy while the cloud provider has an outage, a
dashboard of upstream dependencies, a support bot that explains an error.
Today that means knowing that GitHub's status lives on `githubstatus.com`
and Stripe's on `stripestatus.com`, and writing a parser for every format.
Commercial aggregators maintain thousands of such scrapers.

OSD turns the de facto format into a written spec, and lets each service
announce its document on its own domain.

## Install

```sh
pip install git+https://github.com/AndreaAcanfora/statusdoc
```

## Command line

```sh
statusdoc check github.com npmjs.com             # exit 1 if any is degraded
statusdoc check --fail-on major vercel.com       # only major and critical fail
statusdoc check --json -v github.com             # machine-readable, with components
statusdoc discover fly.io                        # where is the status document?
statusdoc validate status.example.com            # is it conforming?
statusdoc convert status.betterstack.com         # any supported format → OSD JSON
```

Targets are domains (`github.com`), status page URLs or document URLs.
Exit codes of `check`: `0` all fine, `1` at least one service at or above
`--fail-on` (default `minor`), `3` a service could not be reached.

### Hold a deploy during an upstream outage

```yaml
- name: Upstream status
  run: |
    pip install git+https://github.com/AndreaAcanfora/statusdoc
    statusdoc check --fail-on major github.com npmjs.com vercel.com
```

## How documents are found

1. `https://{domain}/.well-known/status`, the discovery URI defined by OSD.
2. A list of known services bundled with the tool (35 services, each verified
   by hand), checked weekly by CI.
3. Conventions: `status.{domain}`, `{name}status.com`, `www.{name}status.com`,
   at `/api/v2/summary.json` (Statuspage shape) or `/index.json` (Better Stack).

Better Stack pages are converted to OSD on the fly. Other formats can be
added as adapters.

## Library

```python
from statusdoc import discover, validate_document

found = discover("github.com")
doc = found.document
print(doc.name, doc.level)  # GitHub operational
for incident in doc.open_incidents:
    print(incident.name, incident.impact, incident.shortlink)
for c in doc.components:
    if c.status != "operational":
        print(c.name, c.status)

issues = validate_document(found.response.json())
```

`doc.level` is one of `operational`, `maintenance`, `minor`, `major`,
`critical`: the publisher's indicator, raised by open incidents and active
maintenance.

## Publishing a conforming status page

If your status page runs on Statuspage or a compatible provider, it most
likely conforms already. Two small additions complete it:

1. **Announce it on your own domain.** Serve this at
   `https://example.com/.well-known/status`, with
   `Content-Type: application/json` and `Access-Control-Allow-Origin: *`:

   ```json
   {
     "osd_version": "0.1",
     "document": "https://status.example.com/api/v2/summary.json",
     "page": "https://status.example.com"
   }
   ```

   With nginx:

   ```nginx
   location = /.well-known/status {
       default_type application/json;
       add_header Access-Control-Allow-Origin *;
       return 200 '{"osd_version":"0.1","document":"https://status.example.com/api/v2/summary.json","page":"https://status.example.com"}';
   }
   ```

2. **Run the validator:** `statusdoc validate example.com`.

If you build your own status page, `Document.to_dict()` produces a
conforming document, and SPEC.md lists every field.

## Status

The spec is a 0.1 draft. The most useful contributions right now are
feedback on the spec, new verified entries for the service list and adapters
for other status page providers.

## Related work

- Atlassian Statuspage's public API, whose `summary.json` shape OSD specifies.
- The expired IETF draft *Service Status Resource Format for Web Services*,
  which proposed a new format instead.
- Aggregators such as StatusGator (commercial) and Statusphere (open source),
  which scrape status pages with one parser per provider.

## License

MIT
