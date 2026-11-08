"""Command line: check, discover, validate and convert status documents."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TextIO

from . import __version__
from .discover import Discovery, DiscoveryError, discover
from .fetch import Fetcher, FetchError, get
from .model import LEVELS, Document
from .validate import Issue, has_errors, validate_document, validate_http

# Exit codes of `statusdoc check`.
EXIT_OK, EXIT_DEGRADED, EXIT_USAGE, EXIT_UNREACHABLE = 0, 1, 2, 3

_SYMBOL = {"operational": "✓", "maintenance": "◷", "minor": "!", "major": "✗", "critical": "✗"}


def main(argv: list[str] | None = None, *, out: TextIO = sys.stdout, fetch: Fetcher = get, registry: dict[str, dict[str, str]] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="statusdoc", description="Read service status pages in the Open Status Document format.")
    parser.add_argument("--version", action="version", version=f"statusdoc {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="show the status of services (exit 1 if one is degraded)")
    p_check.add_argument("targets", nargs="+", metavar="DOMAIN|URL")
    p_check.add_argument("--json", action="store_true", help="print JSON")
    p_check.add_argument("-v", "--verbose", action="store_true", help="list components that are not operational")
    p_check.add_argument(
        "--fail-on", choices=("minor", "major", "critical", "never"), default="minor", help="lowest level that makes the exit code 1 (default: minor)"
    )

    p_disc = sub.add_parser("discover", help="find the status document of services")
    p_disc.add_argument("targets", nargs="+", metavar="DOMAIN|URL")

    p_val = sub.add_parser("validate", help="check a status document against the spec")
    p_val.add_argument("target", metavar="DOMAIN|URL")

    p_conv = sub.add_parser("convert", help="print a status document in OSD form")
    p_conv.add_argument("target", metavar="DOMAIN|URL")

    args = parser.parse_args(argv)
    if out is sys.stdout and hasattr(out, "reconfigure"):
        # Windows consoles and pipes may not encode the status symbols.
        out.reconfigure(errors="replace")
    find = lambda t: discover(t, fetch=fetch, registry=registry)

    if args.command == "check":
        return _check(args, find, out)
    if args.command == "discover":
        status = EXIT_OK
        for target, result in _all(args.targets, find):
            if isinstance(result, Exception):
                print(f"{target}: {result}", file=out)
                status = EXIT_UNREACHABLE
            else:
                print(f"{target}: {result.document_url} (via {result.method}, {result.document.source_format})", file=out)
        return status
    if args.command == "validate":
        return _validate(args.target, find, fetch, out)
    if args.command == "convert":
        try:
            d = find(args.target)
        except (DiscoveryError, FetchError, ValueError) as e:
            print(f"statusdoc: {e}", file=sys.stderr)
            return EXIT_UNREACHABLE
        json.dump(d.document.to_dict(), out, indent=2, ensure_ascii=False)
        print(file=out)
        return EXIT_OK
    return EXIT_USAGE


def _all(targets: list[str], find: Any) -> list[tuple[str, Discovery | Exception]]:
    def one(t: str) -> Discovery | Exception:
        try:
            return find(t)
        except (DiscoveryError, FetchError, ValueError) as e:
            return e

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(zip(targets, pool.map(one, targets)))


def _check(args: argparse.Namespace, find: Any, out: TextIO) -> int:
    results = _all(args.targets, find)
    threshold = len(LEVELS) if args.fail_on == "never" else LEVELS.index(args.fail_on)
    degraded = unreachable = False
    report = []
    for target, r in results:
        if isinstance(r, Exception):
            unreachable = True
            report.append({"target": target, "error": str(r)})
            continue
        d = r.document
        degraded |= d.severity >= threshold
        report.append(_summary(target, r, d))

    if args.json:
        json.dump(report, out, indent=2, ensure_ascii=False)
        print(file=out)
    else:
        width = max(len(t) for t in args.targets)
        for item in report:
            if "error" in item:
                print(f"? {item['target']:<{width}}  unreachable: {item['error']}", file=out)
                continue
            print(f"{_SYMBOL[item['level']]} {item['target']:<{width}}  {item['level']:<11} {item['description']}", file=out)
            for inc in item["incidents"]:
                print(f"  {'':<{width}}  • {inc['name']} ({inc['impact']}, {inc['status']})", file=out)
            for m in item["maintenance"]:
                print(f"  {'':<{width}}  ◷ {m['name']} (until {m['until'] or 'unknown'})", file=out)
            if args.verbose:
                for comp in item["components"]:
                    print(f"  {'':<{width}}  - {comp['name']}: {comp['status']}", file=out)
    if degraded:
        return EXIT_DEGRADED
    return EXIT_UNREACHABLE if unreachable else EXIT_OK


def _summary(target: str, r: Discovery, d: Document) -> dict[str, Any]:
    return {
        "target": target,
        "name": d.name,
        "level": d.level,
        "indicator": d.indicator,
        "description": d.description,
        "page": d.url,
        "document": r.document_url,
        "discovered_via": r.method,
        "incidents": [{"name": i.name, "status": i.status, "impact": i.impact, "url": i.shortlink} for i in d.open_incidents],
        "maintenance": [{"name": m.name, "status": m.status, "until": m.scheduled_until, "url": m.shortlink} for m in d.active_maintenances],
        "components": [{"name": c.name, "status": c.status} for c in d.components if not c.group and c.status != "operational"],
    }


def _validate(target: str, find: Any, fetch: Fetcher, out: TextIO) -> int:
    try:
        r = find(target)
    except (DiscoveryError, FetchError, ValueError) as e:
        print(f"statusdoc: {e}", file=out)
        return EXIT_UNREACHABLE
    print(f"document: {r.document_url} (found via {r.method})", file=out)
    if r.document.source_format != "osd":
        print(f"MUST   $: the document is in the {r.document.source_format} format, not OSD; `statusdoc convert` shows the OSD equivalent", file=out)
        return EXIT_DEGRADED
    issues: list[Issue] = []
    if r.method != "well-known" and "://" not in target:
        issues.append(Issue("SHOULD", "discovery", f"https://{target}/.well-known/status does not point to the document (section 3.1)"))
    resp = r.response or fetch(r.document_url)
    issues += validate_http(resp) + validate_document(resp.json())
    for issue in issues:
        print(issue, file=out)
    errors = sum(i.level == "MUST" for i in issues)
    warnings = len(issues) - errors
    print(f"\n{'not conforming' if has_errors(issues) else 'conforming'} to OSD 0.1: {errors} errors, {warnings} recommendations", file=out)
    return EXIT_DEGRADED if has_errors(issues) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
