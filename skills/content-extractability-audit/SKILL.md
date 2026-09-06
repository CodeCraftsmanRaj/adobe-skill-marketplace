---
name: content-extractability-audit
description: Checks whether the specific facts a person would ask an AI assistant about (price, specs, materials, availability, contact details, key claims) are expressed as plain, unambiguous, readable text, or are instead locked inside images, video, canvas/SVG graphics, or PDF-only downloads where a text-based extractor can't reach them. Also checks heading structure and alt-text coverage as supporting signals. Use this after crawl-render-audit and entity-corroboration-audit to catch facts that are technically on a reachable, readable page but still invisible because of how they're encoded, per Round-2 appendix section C.
license: MIT
allowed-tools: [python3, requests]
---

# Content Extractability Audit

## When to use
A page can pass crawl-render-audit (reachable, server-rendered) and even have some structured
data, and still fail the assistant on the specific fact a user asked about — because that fact
lives only inside a product photo, an infographic, a video, or a PDF spec sheet. This skill
targets exactly the gap described in Round-2 appendix section C: *"the more [a fact is] implied,
buried, or locked inside something non-textual, the more likely it's missed."*

## Inputs
| Field | Type | Required | Notes |
|---|---|---|---|
| `--url` | string | yes | Full URL to audit. |
| `--max-pages` | int | no | Additional same-domain pages to sample (default 8). |
| `--timeout` | int | no | Per-request timeout in seconds (default 10). |
| `--user-agent` | string | no | UA string for the audit's own requests. |

## Procedure
1. Fetch the homepage and up to `max_pages` sampled internal pages (favoring pages that look
   like product/spec pages by URL or link text).
2. **Text-to-markup ratio.** Compute the ratio of visible text length to total HTML size. A very
   low ratio combined with a large number of `<img>`/`<video>`/`<canvas>` elements suggests the
   page leans on non-text media to carry information that should be text.
3. **Fact-pattern-in-image-only check.** Look for strong signals that a *specific, valuable*
   fact is only present as an image: e.g. an `<img>` whose `alt` text (or nearby caption)
   contains a price-like (`$`, `₹`, digits+currency word), spec-like, or contact-like pattern
   that does **not** also appear anywhere in the surrounding plain text — a proxy for "this
   number only exists inside a picture."
4. **Alt-text coverage.** Compute the percentage of `<img>` tags with non-empty, non-generic
   (`"image"`, `"photo"`, filename-as-alt) `alt` attributes. Low coverage is a supporting
   finding, since missing alt text also strips a fallback text channel.
5. **Video-only content.** Flag `<video>` elements with no adjacent descriptive paragraph and no
   `<track kind="captions">`/`<track kind="descriptions">` — key claims narrated only in a video
   with no transcript are invisible to a text extractor.
6. **Canvas/SVG-only content.** Flag `<canvas>` elements (which have zero inherent text content
   for a crawler by construction) used seemingly for infographic-style content, and `<svg>`
   blocks containing `<text>` elements that are visually small/decorative vs. ones that appear
   to carry real data (heuristic on text length and numeric density).
7. **PDF-only facts.** If a page links to a PDF whose link text or context strongly suggests it
   is the *only* place a fact lives (e.g. "Full spec sheet (PDF)" with no equivalent on-page
   text), flag it — noting that a PDF can still be machine-readable text (not necessarily bad),
   but that duplicating the key facts as on-page HTML text is strictly safer for extraction.
8. **Heading structure.** Check for exactly one `<h1>` and a non-decreasing heading hierarchy
   (no `<h3>` before any `<h2>`), since a coherent heading outline helps extractors segment which
   text belongs to which fact/section.
9. Emit one finding per distinct problem, each citing the specific element/snippet found.

## Output
Prints a single JSON object to stdout:
```json
{"skill": "content-extractability-audit", "findings": [ { "id": "CX-001", "title": "...", "severity": "medium", "evidence": "...", "suggested_action": {"summary": "...", "priority": "medium"}, "check_type": "fact-locked-in-image", "page_url": "https://example.com/products/x" } ]}
```
