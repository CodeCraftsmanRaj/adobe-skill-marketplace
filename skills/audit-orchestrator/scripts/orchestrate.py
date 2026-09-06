#!/usr/bin/env python3
"""
audit-orchestrator / orchestrate.py

Entrypoint script for the brand-ai-readiness-audit marketplace.

Runs the other skills' audit scripts as isolated, read-only subprocesses, merges their
findings into the competition's fixed report schema, deduplicates, prioritizes, and prints
the final JSON report to stdout.

Usage:
    python3 orchestrate.py --url https://example.com [--max-pages 8] [--timeout 10] \
        [--user-agent "MyBot/1.0"] [--out report.json]

Exit codes:
    0  audit completed (even if individual sub-skills failed; those show up as meta findings)
    2  invalid input (bad URL)
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_UA = "AdobeHackathonAuditBot/1.0 (+recommend-only; contact=hackathon@adobe.example)"
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SUBSKILL_WALLCLOCK_TIMEOUT = 60  # seconds, hard cap per sub-skill so total stays under 5 min

# Sub-skills in priority order: earlier ones gate later ones (a page a crawler can't reach
# makes structured-data / engagement findings on that page moot), so ties in severity are
# broken by this order.
SUBSKILLS = [
    {
        "id": "crawl-render-audit",
        "script": "skills/crawl-render-audit/scripts/audit_crawl_render.py",
        "category": "discoverability",
    },
    {
        "id": "entity-corroboration-audit",
        "script": "skills/entity-corroboration-audit/scripts/audit_entities.py",
        "category": "discoverability",
    },
    {
        "id": "content-extractability-audit",
        "script": "skills/content-extractability-audit/scripts/audit_extractability.py",
        "category": "discoverability",
    },
    {
        "id": "engagement-continuity-audit",
        "script": "skills/engagement-continuity-audit/scripts/audit_engagement.py",
        "category": "engagement",
    },
]


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty URL")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError("URL has no host")
    return raw


def find_marketplace_root(start: Path) -> Path:
    """Walk upward from this script's location until we find marketplace.json."""
    cur = start.resolve()
    for _ in range(6):
        if (cur / "marketplace.json").exists():
            return cur
        cur = cur.parent
    raise FileNotFoundError("Could not locate marketplace.json above this script")


def run_subskill(root: Path, subskill: dict, url: str, max_pages: int,
                  timeout: int, user_agent: str) -> dict:
    script_path = root / subskill["script"]
    if not script_path.exists():
        return {
            "skill": subskill["id"],
            "findings": [_meta_finding(
                subskill["id"],
                f"Sub-skill script not found at {subskill['script']}"
            )],
        }

    cmd = [
        sys.executable, str(script_path),
        "--url", url,
        "--max-pages", str(max_pages),
        "--timeout", str(timeout),
        "--user-agent", user_agent,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SUBSKILL_WALLCLOCK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {
            "skill": subskill["id"],
            "findings": [_meta_finding(
                subskill["id"],
                f"Sub-skill timed out after {SUBSKILL_WALLCLOCK_TIMEOUT}s and was skipped."
            )],
        }
    except Exception as exc:  # noqa: BLE001 - we want to degrade gracefully, never crash
        return {
            "skill": subskill["id"],
            "findings": [_meta_finding(subskill["id"], f"Sub-skill failed to launch: {exc}")],
        }

    if proc.returncode != 0 or not proc.stdout.strip():
        err_tail = (proc.stderr or "").strip().splitlines()[-3:]
        return {
            "skill": subskill["id"],
            "findings": [_meta_finding(
                subskill["id"],
                f"Sub-skill exited with code {proc.returncode}: {' | '.join(err_tail)}"
            )],
        }

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "skill": subskill["id"],
            "findings": [_meta_finding(subskill["id"], f"Sub-skill emitted invalid JSON: {exc}")],
        }

    payload.setdefault("skill", subskill["id"])
    payload.setdefault("findings", [])
    return payload


def _meta_finding(skill_id: str, message: str) -> dict:
    return {
        "id": "META-001",
        "title": f"{skill_id} could not complete",
        "severity": "low",
        "evidence": message,
        "suggested_action": {
            "summary": "Re-run the audit; if this persists, check network access, robots.txt "
                       "restrictions, or that the target site is reachable.",
            "priority": "low",
        },
        "check_type": "orchestrator-meta",
    }


def dedupe_key(finding: dict) -> tuple:
    return (
        finding.get("check_type", finding.get("title", "")),
        finding.get("page_url", ""),
    )


def merge_and_prioritize(subskill_results: list) -> list:
    merged = []
    for order_idx, result in enumerate(subskill_results):
        skill_id = result.get("skill", "unknown-skill")
        category = next((s["category"] for s in SUBSKILLS if s["id"] == skill_id), "discoverability")
        for f in result.get("findings", []):
            f = dict(f)
            f["source_skill"] = skill_id
            f["source_id"] = f.get("id", "")
            f.setdefault("category", category)
            f["_gate_order"] = order_idx
            merged.append(f)

    # Deduplicate: same (check_type, page_url) -> keep the most severe, merge evidence
    by_key = {}
    for f in merged:
        key = dedupe_key(f)
        if key not in by_key:
            by_key[key] = f
        else:
            existing = by_key[key]
            if SEVERITY_ORDER.get(f.get("severity", "low"), 3) < SEVERITY_ORDER.get(
                existing.get("severity", "low"), 3
            ):
                f["evidence"] = f.get("evidence", "") + " | Also: " + existing.get("evidence", "")
                by_key[key] = f
            else:
                existing["evidence"] = existing.get("evidence", "") + " | Also: " + f.get("evidence", "")

    deduped = list(by_key.values())
    deduped.sort(key=lambda f: (
        SEVERITY_ORDER.get(f.get("severity", "low"), 3),
        f.get("_gate_order", 99),
    ))

    final = []
    for i, f in enumerate(deduped, start=1):
        f.pop("_gate_order", None)
        f.pop("check_type", None)
        f.pop("page_url", None)
        f["id"] = f"F-{i:03d}"
        final.append(f)
    return final


def build_report(site: str, findings: list) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.get("severity", "low")
        counts[sev] = counts.get(sev, 0) + 1

    return {
        "site": site,
        "audited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_findings": len(findings),
            "critical": counts.get("critical", 0),
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
        },
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Brand AI-Readiness Audit orchestrator")
    parser.add_argument("--url", required=True)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    parser.add_argument("--out", default=None, help="Optional path to also save the report JSON")
    args = parser.parse_args()

    try:
        url = normalize_url(args.url)
    except ValueError as exc:
        print(json.dumps({"error": f"invalid --url: {exc}"}), file=sys.stderr)
        return 2

    max_pages = max(1, min(args.max_pages, 15))
    timeout = max(3, min(args.timeout, 20))

    root = find_marketplace_root(Path(__file__).parent)

    site_host = urlparse(url).netloc

    subskill_results = []
    start = time.monotonic()
    for subskill in SUBSKILLS:
        subskill_results.append(
            run_subskill(root, subskill, url, max_pages, timeout, args.user_agent)
        )
    elapsed = time.monotonic() - start

    findings = merge_and_prioritize(subskill_results)
    report = build_report(site_host, findings)
    report["_meta"] = {"runtime_seconds": round(elapsed, 2)}

    out_text = json.dumps(report, indent=2)
    print(out_text)

    if args.out:
        try:
            Path(args.out).write_text(out_text, encoding="utf-8")
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
