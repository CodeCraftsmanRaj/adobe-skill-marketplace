# brand-ai-readiness-audit

**Adobe University Hackathon 2026 — Round 3: Build the Agent Skill Marketplace**

A recommend-only Agent Skill Marketplace that audits any website for both halves of the
Round-2 problem — AI **discoverability** (why an assistant fails to find, read, or cite the
brand) and on-site **engagement** (why a visitor who arrives doesn't stay) — and emits one
structured audit report of findings plus prioritized suggested actions.

Nothing in this marketplace modifies the target site. Every check is a read-only HTTP GET; no
skill authenticates, submits forms, or performs any destructive action.

## Structure

```
brand-ai-readiness-audit/          <- marketplace root (zip this directory)
├── marketplace.json               <- manifest: lists all 5 skills, marks the entrypoint
├── README.md                      <- this file
└── skills/
    ├── audit-orchestrator/            <- ENTRYPOINT: composes the other 4 skills' output
    │   ├── SKILL.md
    │   └── scripts/orchestrate.py
    ├── crawl-render-audit/            <- Can a crawler get in and read the page at all?
    │   ├── SKILL.md
    │   ├── scripts/audit_crawl_render.py
    │   └── references/crawler_matrix.md
    ├── entity-corroboration-audit/    <- Are the facts stated in a trustworthy, current form?
    │   ├── SKILL.md
    │   ├── scripts/audit_entities.py
    │   └── references/schema_rules.md
    ├── content-extractability-audit/  <- Are the actual facts plain text, or locked in media?
    │   ├── SKILL.md
    │   ├── scripts/audit_extractability.py
    │   └── references/extractability_checklist.md
    └── engagement-continuity-audit/   <- Does an arriving visitor stay, once they land?
        ├── SKILL.md
        ├── scripts/audit_engagement.py
        └── references/intent_retention_rubric.md
```

## What each skill does

| Skill | Concern | Key checks |
|---|---|---|
| **audit-orchestrator** *(entrypoint)* | Composition | Runs the 4 skills below as isolated subprocesses, merges + deduplicates + re-prioritizes their findings, emits the single fixed-schema report. Contains no detection logic of its own. |
| **crawl-render-audit** | Off-site discoverability, stage 1 — *can it be reached and read?* | robots.txt rules for named AI bots (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, CCBot, Bytespider, etc.), llms.txt presence, SSR-vs-CSR render-gap heuristic, canonical-tag hygiene, redirect/meta-refresh chains. |
| **entity-corroboration-audit** | Off-site discoverability, stage 2 — *is what's readable trustworthy and current?* | JSON-LD Schema.org validity (Organization/Product/Article required fields), freshness (dateModified vs. today + visible "last updated" signal), sameAs corroboration/disambiguation links, NAP (name/address/phone) consistency between structured data and visible text. |
| **content-extractability-audit** | Off-site discoverability, stage 3 — *is the specific fact plain text, or locked in media?* | text-to-markup ratio, price-like values only present in image alt text, alt-text coverage, video without captions/transcript, canvas/SVG data content, PDF-only spec sheets, heading structure. |
| **engagement-continuity-audit** | On-site engagement — *does an arriving visitor stay?* | broken in-page `#anchor` links, title/meta-description "text scent" vs. actual body content, suspected blocking modals/interstitials on initial load, mobile viewport meta tag, presence of a clear call-to-action. |

## How the entrypoint composes the others

`audit-orchestrator/scripts/orchestrate.py`:

1. Resolves the marketplace root from its own location (via `marketplace.json`), so the
   marketplace works regardless of where it's unzipped.
2. Runs each of the 4 sub-skill scripts as a separate `subprocess`, in discoverability-gate
   order (crawl → entity → extractability → engagement), each with its own hard timeout. A
   sub-skill that errors or times out contributes a single low-severity meta-finding instead of
   aborting the whole audit.
3. Each sub-skill prints one JSON object — `{"skill": "<id>", "findings": [...]}` — to stdout;
   the orchestrator never inspects a sub-skill's internals, only this contract.
4. Merges all findings, tags each with `source_skill` / `source_id` for traceability, assigns
   global sequential IDs (`F-001`, `F-002`, ...).
5. Deduplicates findings that describe the same root cause on the same page (same
   `check_type` + `page_url`), keeping the higher-severity version and merging evidence.
6. Sorts by severity, then by discoverability-gate order within a severity band (a page a
   crawler can't reach makes everything else on it moot).
7. Computes `summary` counts and emits the final report to stdout in the required schema.

## Running it

Requires Python 3.8+ and the `requests` package:

```bash
pip install requests
python3 skills/audit-orchestrator/scripts/orchestrate.py --url https://example.com
```

Optional flags: `--max-pages` (default 8, capped at 15), `--timeout` (per-request seconds,
default 10), `--user-agent`, `--out report.json` to also save a copy to disk. Typical runtime
for a normal marketing/e-commerce site is well under the 5-minute budget.

Each sub-skill script is also independently runnable and spec-compliant on its own, e.g.:

```bash
python3 skills/crawl-render-audit/scripts/audit_crawl_render.py --url https://example.com
```

## Report schema

Every audit produces a JSON object with at least this shape (extra fields — `category`,
`source_skill`, `source_id` — are added but never required by a consumer):

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": { "total_findings": 6, "critical": 1, "high": 2, "medium": 3 },
  "findings": [
    {
      "id": "F-001",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "suggested_action": {
        "summary": "Add Product/Offer JSON-LD to every product page.",
        "priority": "high"
      }
    }
  ]
}
```

## Guardrails

- **Recommend-only.** No skill ever writes to, authenticates against, or otherwise alters the
  target site — every request is a plain read-only HTTP GET.
- **Polite by default.** Every request sets an identifying User-Agent, respects short timeouts,
  and caps the number of internal pages sampled (default 8, hard cap 15) to stay well under the
  5-minute runtime budget and avoid rate abuse.
- **robots.txt-aware.** `crawl-render-audit` reads and reports on robots.txt rules; it does not
  fetch the sample pages used by the other skills through anything other than a normal,
  identified GET request.
- **Graceful degradation.** Any sub-skill failure (timeout, network error, malformed JSON)
  degrades to a single low-severity meta-finding rather than crashing the whole audit.
- **No external services required.** Every skill runs locally against `requests` +
  the Python standard library; the manifest is fully self-contained.
