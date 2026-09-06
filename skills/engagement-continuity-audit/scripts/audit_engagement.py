#!/usr/bin/env python3
"""
engagement-continuity-audit / audit_engagement.py

Read-only checks for: broken in-page anchors, title/meta-description "text scent" mismatch
against actual page content, blocking modal/interstitial patterns present on initial load,
missing mobile viewport meta tag, and absence of a clear call-to-action.

Usage:
    python3 audit_engagement.py --url https://example.com [--max-pages 8] [--timeout 10] \
        [--user-agent "MyBot/1.0"]

Prints: {"skill": "engagement-continuity-audit", "findings": [...]}
"""

import argparse
import json
import re
import sys
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    print(json.dumps({"skill": "engagement-continuity-audit", "findings": [{
        "id": "EG-000", "title": "Missing dependency: requests", "severity": "low",
        "evidence": "The 'requests' package is not installed in this environment.",
        "suggested_action": {"summary": "pip install requests", "priority": "low"},
    }]}))
    sys.exit(0)

TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE
)
META_DESC_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', re.IGNORECASE
)
VIEWPORT_RE = re.compile(
    r'<meta[^>]+name=["\']viewport["\'][^>]+content=["\']([^"\']*)["\']', re.IGNORECASE
)
H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.IGNORECASE | re.DOTALL)
HASH_HREF_RE = re.compile(r'href=["\']#([\w\-]+)["\']', re.IGNORECASE)
ID_RE = re.compile(r'\bid=["\']([\w\-]+)["\']', re.IGNORECASE)
NAME_RE = re.compile(r'\bname=["\']([\w\-]+)["\']', re.IGNORECASE)
NAV_BLOCK_RE = re.compile(r'<nav\b.*?</nav>', re.IGNORECASE | re.DOTALL)
CTA_PATTERNS = re.compile(
    r'\b(buy now|add to cart|contact us|get started|sign up|book now|subscribe|'
    r'learn more|shop now|request a demo|start free trial|download)\b',
    re.IGNORECASE,
)
MODAL_CLASS_RE = re.compile(
    r'class=["\'][^"\']*\b(modal|overlay|popup|interstitial|lightbox)\b[^"\']*["\']',
    re.IGNORECASE,
)
FIXED_STYLE_RE = re.compile(r'position\s*:\s*(fixed|absolute)', re.IGNORECASE)
COOKIE_HINT_RE = re.compile(r'cookie|consent|gdpr', re.IGNORECASE)
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "our", "your", "we", "you", "it", "at", "by", "from", "as", "be", "this", "that",
}


def fetch(url, headers, timeout):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        return resp, None
    except requests.RequestException as exc:
        return None, str(exc)


def extract_links(html, base_url, host, limit):
    links = []
    seen = set()
    for m in re.finditer(r'href=["\']([^"\'#]+)', html, flags=re.IGNORECASE):
        href = m.group(1)
        full = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(full)
        if parsed.netloc != host or parsed.scheme not in ("http", "https"):
            continue
        if full in seen:
            continue
        seen.add(full)
        links.append(full)
        if len(links) >= limit:
            break
    return links


def strip_tags(html: str) -> str:
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def tokenize(text: str):
    words = re.findall(r"[a-zA-Z']{3,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def run_audit(url: str, max_pages: int, timeout: int, user_agent: str) -> list:
    findings = []
    fid = 1

    def add(title, severity, evidence, action_summary, action_priority, check_type, page_url=""):
        nonlocal fid
        findings.append({
            "id": f"EG-{fid:03d}",
            "title": title,
            "severity": severity,
            "evidence": evidence,
            "suggested_action": {"summary": action_summary, "priority": action_priority},
            "check_type": check_type,
            "page_url": page_url,
        })
        fid += 1

    headers = {"User-Agent": user_agent}
    parsed = urlparse(url)
    host = parsed.netloc

    home_resp, home_err = fetch(url, headers, timeout)
    if home_err or home_resp is None or home_resp.status_code >= 400:
        add(
            "Could not fetch homepage to inspect engagement signals",
            "medium",
            f"GET {url} -> {'error: ' + home_err if home_err else home_resp.status_code}",
            "Ensure the page is reachable (see crawl-render-audit) before this check can run.",
            "medium",
            "fetch-error",
            url,
        )
        return findings

    pages = [(url, home_resp.text)]
    for link in extract_links(home_resp.text, url, host, max_pages):
        r, err = fetch(link, headers, timeout)
        if r is not None and err is None and r.status_code < 400:
            pages.append((link, r.text))

    for page_url, html in pages:
        visible_text = strip_tags(html)

        # 1. Deep-link / anchor integrity
        ids_present = set(ID_RE.findall(html)) | set(NAME_RE.findall(html))
        nav_blocks = NAV_BLOCK_RE.findall(html)
        search_space = " ".join(nav_blocks) if nav_blocks else html
        fragments = set(HASH_HREF_RE.findall(search_space))
        broken = sorted(f for f in fragments if f not in ids_present)
        if broken:
            add(
                f"{len(broken)} in-page anchor link(s) point to non-existent targets",
                "medium",
                f"{page_url}: href=\"#{broken[0]}\"" +
                (f" (+{len(broken)-1} more)" if len(broken) > 1 else "") +
                " has no matching id/name on the page.",
                "Fix or remove the broken fragment links so navigation actually scrolls a "
                "visitor to the promised section instead of silently doing nothing.",
                "medium",
                "broken-anchor",
                page_url,
            )

        # 2. Text scent
        title_m = TITLE_RE.search(html)
        desc_m = META_DESC_RE.search(html) or META_DESC_RE_ALT.search(html)
        h1_m = H1_RE.search(html)
        title_text = strip_tags(title_m.group(1)) if title_m else ""
        desc_text = desc_m.group(1).strip() if desc_m else ""
        h1_text = strip_tags(h1_m.group(1)) if h1_m else ""

        if not desc_text:
            add(
                "Missing meta description",
                "low",
                f"{page_url}: no <meta name=\"description\"> found.",
                "Add a concise, accurate meta description — it's often what a visitor (or an "
                "assistant) reads before clicking through, and it sets the expectation the "
                "page then has to satisfy.",
                "low",
                "meta-description-missing",
                page_url,
            )
        else:
            desc_tokens = tokenize(desc_text)
            body_tokens = tokenize(visible_text)
            if desc_tokens:
                overlap = len(desc_tokens & body_tokens) / len(desc_tokens)
                if overlap < 0.3:
                    add(
                        "Meta description doesn't match the page's actual content ('text scent' mismatch)",
                        "medium",
                        f"{page_url}: only {overlap:.0%} of the meaningful words in the meta "
                        f"description ('{desc_text[:80]}...') also appear in the page's visible "
                        "text.",
                        "Rewrite the meta description to accurately reflect what's actually on "
                        "the page. A visitor who arrives expecting one thing and finds another "
                        "leaves immediately — this applies just as much to a visitor dropped in "
                        "by an AI assistant's citation as to one from a search result.",
                        "medium",
                        "text-scent-mismatch",
                        page_url,
                    )

        if not h1_m and not title_m:
            add(
                "Page has neither a <title> nor an <h1> to orient an arriving visitor",
                "high",
                f"{page_url}: no <title> and no <h1> found.",
                "Add a clear <title> and a single <h1> stating what this page is, so a "
                "visitor landing with no prior context can immediately confirm they're in the "
                "right place.",
                "high",
                "no-orientation-heading",
                page_url,
            )

        # 3. Interstitial / modal friction
        modal_hits = MODAL_CLASS_RE.findall(html)
        if modal_hits:
            has_fixed_style = bool(FIXED_STYLE_RE.search(html))
            is_cookie_only = all(
                COOKIE_HINT_RE.search(html[max(0, m.start()-200):m.start()+200])
                for m in MODAL_CLASS_RE.finditer(html)
            )
            if has_fixed_style and not is_cookie_only:
                add(
                    "Page markup suggests a blocking modal/overlay may fire on initial load",
                    "medium",
                    f"{page_url}: found class name(s) matching {sorted(set(modal_hits))} "
                    "combined with fixed/absolute positioning in the initial HTML.",
                    "Confirm (manually or via a headless-browser check) whether this overlay "
                    "fires immediately on load and blocks content. If so, delay it, make it "
                    "dismissible with one click, or remove it — an immediate blocking overlay "
                    "is one of the most common bounce triggers for visitors arriving with a "
                    "specific fact in mind.",
                    "medium",
                    "blocking-interstitial-suspected",
                    page_url,
                )

        # 4. Mobile readiness
        vp_m = VIEWPORT_RE.search(html)
        if not vp_m:
            add(
                "Missing mobile viewport meta tag",
                "medium",
                f"{page_url}: no <meta name=\"viewport\"> found.",
                "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">. "
                "A large share of assistant-referred traffic is mobile, and its absence "
                "typically means the page renders unusably small/wide on a phone.",
                "medium",
                "viewport-missing",
                page_url,
            )
        elif "width=device-width" not in vp_m.group(1).replace(" ", ""):
            add(
                "Viewport meta tag present but not configured for responsive rendering",
                "low",
                f"{page_url}: viewport content is \"{vp_m.group(1)}\".",
                "Set the viewport content to include width=device-width, initial-scale=1 for "
                "correct mobile scaling.",
                "low",
                "viewport-misconfigured",
                page_url,
            )

        # 5. Clear next step / CTA
        if not CTA_PATTERNS.search(visible_text):
            add(
                "No clear call-to-action text found on the page",
                "medium",
                f"{page_url}: none of the common CTA phrases (buy now, contact us, get "
                "started, sign up, learn more, etc.) were found in the visible text.",
                "Add an explicit, unambiguous next step near the top of the page (e.g. a "
                "'Contact us' or 'Get started' button/link) — a visitor who is oriented but "
                "sees no obvious action still tends to leave.",
                "medium",
                "no-cta",
                page_url,
            )

    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--user-agent", default="AdobeHackathonAuditBot/1.0 (+recommend-only)")
    args = parser.parse_args()

    findings = run_audit(args.url, args.max_pages, args.timeout, args.user_agent)
    print(json.dumps({"skill": "engagement-continuity-audit", "findings": findings}))


if __name__ == "__main__":
    main()
