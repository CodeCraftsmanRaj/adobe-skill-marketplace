#!/usr/bin/env python3
"""
content-extractability-audit / audit_extractability.py

Read-only checks for: facts locked inside images/video/canvas/SVG/PDF-only content instead of
plain text, alt-text coverage, and heading structure.

Usage:
    python3 audit_extractability.py --url https://example.com [--max-pages 8] [--timeout 10] \
        [--user-agent "MyBot/1.0"]

Prints: {"skill": "content-extractability-audit", "findings": [...]}
"""

import argparse
import json
import re
import sys
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    print(json.dumps({"skill": "content-extractability-audit", "findings": [{
        "id": "CX-000", "title": "Missing dependency: requests", "severity": "low",
        "evidence": "The 'requests' package is not installed in this environment.",
        "suggested_action": {"summary": "pip install requests", "priority": "low"},
    }]}))
    sys.exit(0)

IMG_RE = re.compile(r'<img\b([^>]*)>', re.IGNORECASE)
ATTR_RE = re.compile(r'(\w[\w\-]*)\s*=\s*"([^"]*)"|(\w[\w\-]*)\s*=\s*\'([^\']*)\'', re.IGNORECASE)
VIDEO_BLOCK_RE = re.compile(r'<video\b.*?</video>', re.IGNORECASE | re.DOTALL)
TRACK_RE = re.compile(r'<track\b[^>]*kind=["\'](captions|descriptions)["\']', re.IGNORECASE)
CANVAS_RE = re.compile(r'<canvas\b[^>]*>', re.IGNORECASE)
SVG_BLOCK_RE = re.compile(r'<svg\b.*?</svg>', re.IGNORECASE | re.DOTALL)
SVG_TEXT_RE = re.compile(r'<text\b[^>]*>(.*?)</text>', re.IGNORECASE | re.DOTALL)
PDF_LINK_RE = re.compile(
    r'<a\b([^>]*href=["\']([^"\']+\.pdf)["\'][^>]*)>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
HEADING_RE = re.compile(r'<h([1-6])\b[^>]*>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)
PRICE_PATTERN = re.compile(r'(?:\$|₹|USD|INR|EUR|£)\s?\d[\d,]*(?:\.\d+)?')
GENERIC_ALT = {"", "image", "photo", "picture", "img", "banner", "logo image"}


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
        if full in seen or full.lower().endswith(".pdf"):
            continue
        seen.add(full)
        score = 1 if any(kw in full.lower() for kw in ("product", "shop", "spec", "detail")) else 0
        links.append((score, full))
        if len(links) >= limit * 4:
            break
    links.sort(key=lambda t: -t[0])
    return [u for _, u in links[:limit]]


def parse_attrs(attr_str: str) -> dict:
    attrs = {}
    for m in ATTR_RE.finditer(attr_str):
        if m.group(1):
            attrs[m.group(1).lower()] = m.group(2)
        else:
            attrs[m.group(3).lower()] = m.group(4)
    return attrs


def strip_tags(html: str) -> str:
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def looks_like_filename(alt: str) -> bool:
    return bool(re.match(r'^[\w\-]+\.(jpg|jpeg|png|gif|webp|svg)$', alt.strip(), re.IGNORECASE))


def run_audit(url: str, max_pages: int, timeout: int, user_agent: str) -> list:
    findings = []
    fid = 1

    def add(title, severity, evidence, action_summary, action_priority, check_type, page_url=""):
        nonlocal fid
        findings.append({
            "id": f"CX-{fid:03d}",
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
            "Could not fetch homepage to inspect content extractability",
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
        visible_len = len(visible_text)
        html_len = max(len(html), 1)
        ratio = visible_len / html_len

        imgs = [parse_attrs(m.group(1)) for m in IMG_RE.finditer(html)]
        videos = VIDEO_BLOCK_RE.findall(html)
        canvases = CANVAS_RE.findall(html)
        svgs = SVG_BLOCK_RE.findall(html)

        media_count = len(imgs) + len(videos) + len(canvases) + len(svgs)
        if ratio < 0.08 and media_count >= 5:
            add(
                "Very low text-to-markup ratio alongside heavy media use",
                "medium",
                f"{page_url}: visible text is only {ratio:.1%} of page size, alongside "
                f"{len(imgs)} images, {len(videos)} videos, {len(canvases)} canvas element(s), "
                f"{len(svgs)} inline SVG(s).",
                "Audit whether facts a customer would ask about (price, specs, materials, "
                "availability) are duplicated as plain text somewhere on the page, not only "
                "conveyed visually.",
                "medium",
                "low-text-ratio",
                page_url,
            )

        # Alt text coverage + price-like facts only in alt/caption
        if imgs:
            non_empty_alt = [i for i in imgs if i.get("alt", "").strip()]
            meaningful_alt = [
                i for i in non_empty_alt
                if i.get("alt", "").strip().lower() not in GENERIC_ALT
                and not looks_like_filename(i.get("alt", ""))
            ]
            coverage = len(meaningful_alt) / len(imgs)
            if coverage < 0.5:
                add(
                    f"Low meaningful alt-text coverage ({coverage:.0%}) across {len(imgs)} images",
                    "low",
                    f"{page_url}: only {len(meaningful_alt)}/{len(imgs)} <img> tags have "
                    "descriptive, non-generic alt text.",
                    "Write specific alt text for content-bearing images (what the product is, "
                    "key visible attributes) — it's a fallback text channel for any extractor "
                    "that can't process the image itself.",
                    "low",
                    "low-alt-coverage",
                    page_url,
                )
            for i in imgs:
                alt = i.get("alt", "")
                alt_price_match = PRICE_PATTERN.search(alt)
                if alt_price_match and alt_price_match.group(0) not in visible_text:
                    add(
                        "Price-like value appears only in image alt text, not in visible page text",
                        "high",
                        f"{page_url}: alt=\"{alt}\" contains a price pattern not otherwise "
                        "found in the page's plain text.",
                        "State the price as plain, visible HTML text (not only inside an image "
                        "or its alt attribute) so it can be extracted, quoted, and kept current "
                        "without re-rendering an image.",
                        "high",
                        "fact-locked-in-image",
                        page_url,
                    )
                    break  # one representative finding per page is enough signal

        # Video-only content
        for vid_html in videos:
            has_track = bool(TRACK_RE.search(vid_html))
            if not has_track:
                add(
                    "Video content has no captions/description track",
                    "medium",
                    f"{page_url}: a <video> element has no <track kind=\"captions\"> or "
                    "\"descriptions\" child.",
                    "Add a captions or descriptions track (or at minimum a text transcript "
                    "elsewhere on the page) for any video that communicates claims a user might "
                    "ask an assistant about.",
                    "medium",
                    "video-no-transcript",
                    page_url,
                )
                break

        # Canvas used for content
        if canvases:
            add(
                f"Page uses <canvas> element(s) ({len(canvases)}) which carry no inherent text",
                "low",
                f"{page_url}: {len(canvases)} <canvas> element(s) found; canvas content is "
                "pixels, not DOM text, and is invisible to any text-based extractor by "
                "construction.",
                "If canvas is used for a chart/infographic conveying real facts (not just a "
                "game or decorative animation), duplicate the underlying data as an HTML "
                "table or plain text caption nearby.",
                "low",
                "canvas-content",
                page_url,
            )

        # SVG with meaningful text vs decorative
        for svg in svgs:
            texts = SVG_TEXT_RE.findall(svg)
            joined = " ".join(re.sub(r'<[^>]+>', '', t) for t in texts).strip()
            digit_count = sum(c.isdigit() for c in joined)
            if len(joined) > 40 and digit_count >= 3:
                add(
                    "Inline SVG appears to carry substantive data via <text> elements",
                    "low",
                    f"{page_url}: an <svg> block contains {len(joined)} chars of <text> "
                    f"content with {digit_count} digit characters (looks data-bearing, e.g. a "
                    "chart or spec diagram).",
                    "Confirm this data is also available as plain HTML text/table nearby; SVG "
                    "text extraction support varies across crawlers and is not guaranteed.",
                    "low",
                    "svg-data-content",
                    page_url,
                )
                break

        # PDF-only facts
        for m in PDF_LINK_RE.finditer(html):
            link_text = strip_tags(m.group(3))
            href = m.group(2)
            if re.search(r'(spec|datasheet|data sheet|full details|brochure)', link_text, re.IGNORECASE):
                add(
                    "Key facts may live only inside a linked PDF, not on-page text",
                    "low",
                    f"{page_url}: link \"{link_text.strip()}\" -> {href} suggests spec/detail "
                    "content that may not be duplicated as on-page HTML text.",
                    "Duplicate the key facts (dimensions, materials, certifications) as plain "
                    "HTML text on the page itself; keep the PDF as a supplementary download "
                    "rather than the only source.",
                    "low",
                    "pdf-only-facts",
                    page_url,
                )
                break

        # Heading structure
        headings = [(int(lvl), strip_tags(txt)) for lvl, txt in HEADING_RE.findall(html)]
        h1_count = sum(1 for lvl, _ in headings if lvl == 1)
        if h1_count == 0:
            add(
                "Page has no <h1>",
                "low",
                f"{page_url}: 0 <h1> elements found among {len(headings)} total headings.",
                "Add exactly one <h1> stating the page's primary subject, giving extractors a "
                "clear anchor for what the page is about.",
                "low",
                "heading-no-h1",
                page_url,
            )
        elif h1_count > 1:
            add(
                f"Page has {h1_count} <h1> elements (should have exactly one)",
                "low",
                f"{page_url}: multiple <h1> tags found.",
                "Consolidate to a single <h1>; use <h2>/<h3> for subsections.",
                "low",
                "heading-multiple-h1",
                page_url,
            )

        prev_level = 0
        skipped = False
        for lvl, _ in headings:
            if prev_level and lvl > prev_level + 1:
                skipped = True
                break
            prev_level = lvl
        if skipped:
            add(
                "Heading hierarchy skips levels (e.g. h2 followed directly by h4)",
                "low",
                f"{page_url}: heading sequence is {[l for l, _ in headings]}.",
                "Keep heading levels sequential so an extractor's section segmentation "
                "reflects the page's actual structure.",
                "low",
                "heading-hierarchy-skip",
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
    print(json.dumps({"skill": "content-extractability-audit", "findings": findings}))


if __name__ == "__main__":
    main()
