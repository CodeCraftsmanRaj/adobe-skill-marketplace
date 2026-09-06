---
name: entity-corroboration-audit
description: Extracts and validates schema.org JSON-LD structured data (Organization, Product, Offer, LocalBusiness, Article, FAQPage), checks fact freshness (dateModified/datePublished vs today, and whether the page gives any human-visible "last updated" signal), checks entity-disambiguation signals (sameAs links to authoritative external profiles such as Wikidata/Wikipedia/LinkedIn/crunchbase, and a distinguishing legalName/description), and cross-checks NAP (name/address/phone) consistency between the page's visible text and its own structured data. Use this after crawl-render-audit confirms a page is reachable and readable, to check whether the facts on it are stated in a form machines trust and can date/attribute correctly.
license: MIT
allowed-tools: [python3, requests]
---

# Entity & Corroboration Audit

## When to use
Run this after `crawl-render-audit` establishes a page can be reached and read. This skill asks
the next question: **of what's readable, is it stated in a form an AI assistant will trust,
attribute correctly, and treat as current?** This covers structured-data validity, freshness,
and entity disambiguation/corroboration signals — the mechanisms described in the Round-2
appendix sections B, C, and D (source selection favors easily-quoted facts; agreement across
sources and unambiguous identity increase trust; explicit plain-text/structured facts beat
implied ones).

## Inputs
| Field | Type | Required | Notes |
|---|---|---|---|
| `--url` | string | yes | Full URL to audit (homepage or a representative product/about page). |
| `--max-pages` | int | no | Additional same-domain pages to sample (default 8). |
| `--timeout` | int | no | Per-request timeout in seconds (default 10). |
| `--user-agent` | string | no | UA string for the audit's own requests. |

## Procedure
1. Fetch the homepage and up to `max_pages` sampled internal pages (prioritizing links whose
   URL or anchor text suggests product, pricing, or about/contact content).
2. **Extract every `<script type="application/ld+json">` block** per page and parse it as JSON
   (tolerating a top-level array or a `@graph` wrapper). Track parse failures separately from
   "none found."
3. **Validate required fields** for whichever schema.org `@type`s are present:
   - `Organization` / `LocalBusiness`: `name`, `url`; recommended: `logo`, `address`,
     `telephone`, `sameAs`.
   - `Product`: `name`, `offers` (with `price` and `priceCurrency`, or `lowPrice`/`highPrice`);
     recommended: `sku` or `gtin`/`mpn`, `aggregateRating` only if truthful/present elsewhere.
   - `Article` / `BlogPosting`: `headline`, `datePublished`; recommended: `dateModified`,
     `author`.
   Flag missing required fields as findings; flag missing recommended fields as lower-severity
   proactive suggestions.
4. **Freshness check.** For each page with a date field (structured `dateModified`/
   `datePublished`, or `<meta property="article:modified_time">`, or a human-visible "Last
   updated" / "Updated on" string near the top of the content), compare to the audit's run date.
   Flag content older than ~12 months **and** with zero freshness signal (no date field, no
   visible "updated" text) as a stale-and-uncorroborated risk — the reasoning being that an
   assistant weighing conflicting facts from multiple sources will favor ones it can date, and
   penalize ones it can't.
5. **Disambiguation / corroboration signals.** Check for `sameAs` (or equivalent visible links)
   pointing to recognizable authoritative profiles (Wikidata, Wikipedia, LinkedIn company page,
   Crunchbase, official social profiles). Flag their total absence as medium severity when the
   brand name is short/generic (higher collision risk) and low severity otherwise.
6. **NAP consistency.** Regex-extract phone-number-like and address-like strings from the
   visible page text (e.g. footer/contact areas) and compare against any `telephone`/`address`
   found in structured data on the same page. Flag mismatches — inconsistent facts about the
   same entity across the same page undermine the exact kind of cross-source agreement described
   in appendix D.
7. Emit one finding per distinct problem with concrete evidence (the offending JSON-LD snippet
   summary, the parsed date, the mismatched strings, etc.).

## Output
Prints a single JSON object to stdout:
```json
{"skill": "entity-corroboration-audit", "findings": [ { "id": "EC-001", "title": "...", "severity": "high", "evidence": "...", "suggested_action": {"summary": "...", "priority": "high"}, "check_type": "jsonld-missing-required-field", "page_url": "https://example.com/products/x" } ]}
```
