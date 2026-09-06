---
name: crawl-render-audit
description: Checks whether AI crawlers and search bots can even get in and read a website — robots.txt rules for named AI-assistant user agents (GPTBot, ChatGPT-User, ClaudeBot, anthropic-ai, PerplexityBot, Google-Extended, CCBot, Bytespider), presence and validity of an llms.txt file, whether the page's meaningful content is present in the raw server-rendered HTML or only assembled client-side after JavaScript runs, canonical-tag hygiene, and redirect/meta-refresh chains that can strand a crawler. Use this as the first-stage discoverability check, since a page a crawler cannot reach or read makes every downstream check (structured data, freshness, engagement) moot for that page.
license: MIT
allowed-tools: [python3, requests]
---

# Crawl & Render Audit

## When to use
Use this skill first when auditing a site for AI discoverability. It answers the most basic
question from the discoverability model: **can an automated reader get in, and can it read
what's there?** If this stage fails for a page, downstream checks (structured data quality,
freshness, engagement) are moot for that page — the content is invisible before it can even be
evaluated.

## Inputs
| Field | Type | Required | Notes |
|---|---|---|---|
| `--url` | string | yes | Full URL to audit. |
| `--max-pages` | int | no | Max additional internal links to sample beyond the homepage (default 8). |
| `--timeout` | int | no | Per-request timeout in seconds (default 10). |
| `--user-agent` | string | no | UA string used for the audit's own (polite, read-only) requests. |

## Procedure
1. **Fetch `/robots.txt`** with a short timeout. Parse it (not just for `*`, but per-user-agent
   sections) for the wildcard agent and each of: `GPTBot`, `ChatGPT-User`, `ClaudeBot`,
   `anthropic-ai`, `PerplexityBot`, `Google-Extended`, `CCBot`, `Bytespider`, `Applebot-Extended`.
   Flag any of these blocked from the site's key content paths (an explicit `Disallow: /` under
   that agent, or under `*` with no override), since a blocked bot cannot cite the brand at all
   regardless of content quality.
2. **Check for `/llms.txt`.** If present, validate it's plain text with at least one markdown
   heading and one link — a signal the site has deliberately curated what an LLM should read.
   Its absence is a low-severity opportunity, not a defect (it's an emerging, optional
   convention).
3. **Fetch the homepage's raw HTML** (no JS execution — this mirrors how a lightweight crawler,
   as opposed to a full headless browser, reads the page) and up to `max_pages` same-domain
   links discovered on it.
4. **Render-gap heuristic**, per fetched page: strip `<script>`/`<style>` content, measure the
   remaining visible text length. Flag as high severity if visible text is very small (e.g.
   under ~150 characters) while the page nonetheless has substantial `<script>` payload and a
   near-empty root container (`id="root"`, `id="app"`, `id="__next"`, etc.) — the classic sign
   that content is assembled client-side and a text-only crawler sees almost nothing.
5. **Canonical hygiene.** Check each fetched page for a `<link rel="canonical">`; flag if
   missing, if it points to a different (non-self, non-obviously-intentional) URL without clear
   reason, or if multiple conflicting canonical tags exist.
6. **Redirect / meta-refresh chains.** Follow redirects (capped) and flag long chains (3+ hops)
   or a client-side `<meta http-equiv="refresh">` used in place of a proper HTTP redirect, both
   of which can strand simple crawlers.
7. Emit one finding per distinct problem, each with the specific evidence gathered (status
   codes, byte counts, matched robots.txt lines, etc.).

## Output
Prints a single JSON object to stdout:
```json
{"skill": "crawl-render-audit", "findings": [ { "id": "CR-001", "title": "...", "severity": "high", "evidence": "...", "suggested_action": {"summary": "...", "priority": "high"}, "check_type": "robots-ai-bot-block", "page_url": "https://example.com/" } ]}
```
`check_type` and `page_url` are extra fields used by the orchestrator for deduplication; they
are additive, not a departure from the required schema.
