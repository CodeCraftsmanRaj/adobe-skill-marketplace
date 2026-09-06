---
name: audit-orchestrator
description: Entrypoint skill for the Brand AI-Readiness Audit marketplace. Given a website URL, invokes the crawl-render-audit, entity-corroboration-audit, content-extractability-audit, and engagement-continuity-audit skills as read-only subprocesses, merges their findings, deduplicates and re-prioritizes them, and emits a single audit report against the competition's fixed JSON schema (site, audited_at, summary, findings[]). Use this skill whenever an agent is asked to audit, diagnose, or score a brand's website for AI discoverability (why it isn't found or cited by AI assistants) or on-site engagement (why visitors who arrive don't stay), and needs one consolidated, evidence-backed, prioritized report rather than raw output from each individual check.
license: MIT
allowed-tools: [python3, subprocess, requests, bs4]
---

# Audit Orchestrator (entrypoint)

## When to use
Use this skill when you have a target website (a URL or bare domain) and need a single,
structured audit report covering both halves of brand AI-readiness:

- **Off-site discoverability** — why an AI assistant would fail to find, read, or cite the brand.
- **On-site engagement** — why a visitor who does land on the site (frequently via an AI
  assistant's citation, arriving with no prior context) bounces instead of staying.

This is the only skill in the marketplace an outside agent should invoke directly. It does not
duplicate any detection logic itself — its job is orchestration, deduplication, prioritization,
and schema compliance.

## Inputs
| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | string | yes | A full URL (`https://example.com`) or bare domain (`example.com`, normalized to `https://`). |
| `max_pages` | integer | no | Max pages each sub-skill may crawl beyond the homepage (default 8, hard cap 15, keeps total runtime under 5 minutes). |
| `timeout_seconds` | integer | no | Per-HTTP-request timeout passed to every sub-skill (default 10). |
| `user_agent` | string | no | Override the default polite UA string (default `AdobeHackathonAuditBot/1.0 (+recommend-only; contact=hackathon@adobe.example)`). |

## Procedure
1. **Normalize input.** Ensure the URL has a scheme; reject non-http(s) schemes; resolve to a
   canonical host for reporting as `site`.
2. **Resolve sibling skill paths.** From this skill's own folder, walk up to the marketplace
   root (the parent of `skills/`) using `marketplace.json` to look up each non-entrypoint
   skill's `scripts/` entry script. This keeps the orchestrator working regardless of where the
   marketplace root is unzipped.
3. **Run each sub-skill as an isolated, read-only subprocess** with a hard wall-clock timeout,
   passing `url`, `max_pages`, `timeout_seconds`, `user_agent` as CLI flags:
   - `crawl-render-audit/scripts/audit_crawl_render.py`
   - `entity-corroboration-audit/scripts/audit_entities.py`
   - `content-extractability-audit/scripts/audit_extractability.py`
   - `engagement-continuity-audit/scripts/audit_engagement.py`
   Each sub-skill prints one JSON object to stdout: `{"skill": "<id>", "findings": [...]}`.
   A sub-skill that errors or times out contributes zero findings plus one `low`-severity
   `meta` finding noting the tool failure — it never aborts the whole audit.
4. **Merge findings.** Concatenate every sub-skill's findings, tag each with its
   `source_skill`, and assign globally sequential IDs (`F-001`, `F-002`, ...) while preserving
   the sub-skill's own local ID as `source_id` for traceability.
5. **Deduplicate.** If two findings from different sub-skills describe the same underlying root
   cause on the same page (matched by a normalized `(check_type, url)` key), keep the
   higher-severity one and merge the evidence.
6. **Prioritize.** Sort findings by severity (`critical` > `high` > `medium` > `low`), and
   within a severity band, put discoverability-blocking findings (crawl/render access) ahead of
   downstream ones (a page a crawler can't reach makes every other finding on it moot).
7. **Compute summary counts** (`total_findings`, `critical`, `high`, `medium`) from the merged,
   deduplicated list.
8. **Assemble the final report** against the fixed schema below and print it as the skill's
   sole stdout output (plus, if writable, save a copy to `./audit-report-<host>-<timestamp>.json`
   for convenience — never write anywhere outside the current working directory).

## Output
A single JSON object, minimum required shape (additional fields are allowed and several are
added — `source_skill`, `source_id`, `category` — but never removed):

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": {
    "total_findings": 6,
    "critical": 1,
    "high": 2,
    "medium": 3
  },
  "findings": [
    {
      "id": "F-001",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "suggested_action": {
        "summary": "Add Product/Offer JSON-LD to every product page.",
        "priority": "high"
      },
      "category": "discoverability",
      "source_skill": "entity-corroboration-audit",
      "source_id": "EC-003"
    }
  ]
}
```

No skill invoked by this orchestrator ever mutates the target site, submits forms, authenticates,
or writes files outside the sandbox working directory.
