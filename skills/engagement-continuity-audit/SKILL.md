---
name: engagement-continuity-audit
description: Checks whether a visitor who lands on the site — often dropped in cold from an AI assistant's citation, with none of the conversational context that got them there — is oriented and able to keep going instead of bouncing. Covers deep-link/anchor integrity (do #fragment links in navigation actually resolve to a real target on the page), text scent (does the title/meta-description/H1 actually match what's on the page, so the visitor lands where they expected), interstitial and modal friction (cookie banners, popups, overlays that block content on arrival), mobile viewport readiness, and presence of a clear next-step call to action. Use this to cover the on-site-engagement half of the audit, complementing the three discoverability skills.
license: MIT
allowed-tools: [python3, requests]
---

# Engagement Continuity Audit

## When to use
Use this to cover the second half of the Round-2 problem: **why does a visitor who arrives not
stay?** This matters especially for traffic arriving from an AI assistant, which typically drops
a visitor directly onto a specific page or anchor with none of the back-and-forth context that
led them there — so the page itself has to do all the orienting work a human salesperson or a
prior search-results snippet might otherwise have done.

## Inputs
| Field | Type | Required | Notes |
|---|---|---|---|
| `--url` | string | yes | Full URL to audit. |
| `--max-pages` | int | no | Additional same-domain pages to sample (default 8). |
| `--timeout` | int | no | Per-request timeout in seconds (default 10). |
| `--user-agent` | string | no | UA string for the audit's own requests. |

## Procedure
1. Fetch the homepage and up to `max_pages` sampled internal pages.
2. **Deep-link / anchor integrity.** Collect every same-page `href="#fragment"` link found in
   navigation/menu markup, and check the corresponding `id="fragment"` (or `name="fragment"`)
   actually exists somewhere on the page. A visitor (or an assistant) sent to `page#section`
   should land exactly where promised — a broken anchor drops them at the top with no idea
   where to look.
3. **Text scent.** Extract `<title>`, `<meta name="description">`, and the first `<h1>`.
   Compute a simple keyword-overlap score between the meta description and the page's own
   visible body text. A low-overlap description (i.e., it promises something the page doesn't
   actually deliver) is flagged, since mismatched scent is a classic bounce trigger — the
   visitor's first impression contradicts what they actually find.
4. **Interstitial / modal friction.** Scan for common patterns indicating a blocking overlay
   fires on load: high z-index fixed/absolute-positioned elements combined with common
   modal/overlay class or id naming (`modal`, `overlay`, `popup`, `interstitial`, `lightbox`)
   that appear in the initial HTML (i.e., not something the user has to trigger), plus
   known exit-intent script signatures. Cookie-consent banners are treated separately and only
   flagged if they appear to block the full viewport rather than a slim bar.
5. **Mobile readiness.** Check for a `<meta name="viewport">` tag with a sensible
   `width=device-width` value; its absence strongly correlates with poor mobile rendering and
   is a well-established bounce driver for the large share of assistant-referred mobile traffic.
6. **Clear next step.** Search the visible text and prominent link/button text for common
   call-to-action patterns (buy, add to cart, contact, get started, sign up, book, subscribe,
   learn more, download). Flag pages with none found near the top of the content — a visitor
   who's oriented but has no obvious next action is still likely to leave.
7. Emit one finding per distinct problem with concrete evidence.

## Output
Prints a single JSON object to stdout:
```json
{"skill": "engagement-continuity-audit", "findings": [ { "id": "EG-001", "title": "...", "severity": "medium", "evidence": "...", "suggested_action": {"summary": "...", "priority": "medium"}, "check_type": "broken-anchor", "page_url": "https://example.com/" } ]}
```
