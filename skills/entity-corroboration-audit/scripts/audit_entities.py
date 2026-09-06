#!/usr/bin/env python3
"""
entity-corroboration-audit / audit_entities.py

Read-only checks for: JSON-LD schema.org validity, fact freshness, entity-disambiguation /
corroboration signals (sameAs), and NAP (name/address/phone) consistency between visible text
and structured data.

Usage:
    python3 audit_entities.py --url https://example.com [--max-pages 8] [--timeout 10] \
        [--user-agent "MyBot/1.0"]

Prints: {"skill": "entity-corroboration-audit", "findings": [...]}
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    print(json.dumps({"skill": "entity-corroboration-audit", "findings": [{
        "id": "EC-000", "title": "Missing dependency: requests", "severity": "low",
        "evidence": "The 'requests' package is not installed in this environment.",
        "suggested_action": {"summary": "pip install requests", "priority": "low"},
    }]}))
    sys.exit(0)

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
MODIFIED_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
UPDATED_TEXT_RE = re.compile(
    r'(last\s+updated|updated\s+on|last\s+modified)[:\s]*'
    r'([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)
PHONE_RE = re.compile(r'(\+?\d[\d\-\.\(\)\s]{7,}\d)')
AUTHORITATIVE_DOMAINS = (
    "wikidata.org", "wikipedia.org", "linkedin.com/company", "crunchbase.com",
    "instagram.com", "facebook.com", "twitter.com", "x.com", "youtube.com",
)
SAMEAS_RE = re.compile(r'"sameAs"\s*:\s*(\[[^\]]*\]|"[^"]*")', re.IGNORECASE)


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
        score = 0
        low = full.lower()
        for kw in ("product", "shop", "pricing", "price", "about", "contact", "company"):
            if kw in low:
                score += 1
        links.append((score, full))
        if len(links) >= limit * 4:
            break
    links.sort(key=lambda t: -t[0])
    return [u for _, u in links[:limit]]


def strip_tags(html: str) -> str:
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def load_jsonld_blocks(html: str):
    blocks = []
    for m in JSONLD_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            blocks.append({"_parse_error": True, "_raw_snippet": raw[:200]})
            continue
        if isinstance(data, list):
            blocks.extend([d for d in data if isinstance(d, dict)])
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                blocks.extend([d for d in data["@graph"] if isinstance(d, dict)])
            else:
                blocks.append(data)
    return blocks


def get_type(block: dict):
    t = block.get("@type", "")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def parse_date(value: str):
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                "%B %d, %Y", "%b %d, %Y", "%b. %d, %Y"):
        try:
            dt = datetime.strptime(value[:len(value)], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', value)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def run_audit(url: str, max_pages: int, timeout: int, user_agent: str) -> list:
    findings = []
    fid = 1

    def add(title, severity, evidence, action_summary, action_priority, check_type, page_url=""):
        nonlocal fid
        findings.append({
            "id": f"EC-{fid:03d}",
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
    origin = f"{parsed.scheme}://{parsed.netloc}"
    host = parsed.netloc

    home_resp, home_err = fetch(url, headers, timeout)
    if home_err or home_resp is None or home_resp.status_code >= 400:
        add(
            "Could not fetch homepage to inspect structured data",
            "medium",
            f"GET {url} -> {'error: ' + home_err if home_err else home_resp.status_code}",
            "Ensure the page is reachable (see crawl-render-audit) before structured data can "
            "be evaluated.",
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

    now = datetime.now(timezone.utc)
    org_like_found = False
    brand_name_guess = None

    for page_url, html in pages:
        blocks = load_jsonld_blocks(html)
        parse_errors = [b for b in blocks if b.get("_parse_error")]
        real_blocks = [b for b in blocks if not b.get("_parse_error")]

        if parse_errors:
            add(
                f"{len(parse_errors)} JSON-LD block(s) fail to parse as valid JSON",
                "high",
                f"{page_url}: snippet starts with: {parse_errors[0]['_raw_snippet']!r}",
                "Fix the malformed JSON-LD (common causes: trailing commas, unescaped quotes "
                "inside string values, template-engine artifacts left in the output). Validate "
                "with a JSON-LD linter before shipping.",
                "high",
                "jsonld-parse-error",
                page_url,
            )

        if not real_blocks:
            add(
                "No valid JSON-LD structured data found on page",
                "high",
                f"{page_url}: 0 parsable <script type=\"application/ld+json\"> blocks.",
                "Add schema.org JSON-LD appropriate to the page (Organization on the homepage, "
                "Product on product pages, Article on blog posts) so AI assistants can extract "
                "brand and product facts without guessing from prose.",
                "high",
                "jsonld-missing",
                page_url,
            )
            continue

        for block in real_blocks:
            types = get_type(block)

            if any(t in ("Organization", "LocalBusiness", "Corporation") for t in types):
                org_like_found = True
                brand_name_guess = brand_name_guess or block.get("name")
                missing = [f for f in ("name", "url") if not block.get(f)]
                if missing:
                    add(
                        f"Organization structured data missing required field(s): {', '.join(missing)}",
                        "high",
                        f"{page_url}: Organization block has keys {sorted(block.keys())}",
                        f"Add {', '.join(missing)} to the Organization JSON-LD block.",
                        "high",
                        "jsonld-missing-required-field",
                        page_url,
                    )
                if not block.get("sameAs"):
                    add(
                        "Organization structured data has no sameAs corroboration links",
                        "medium",
                        f"{page_url}: Organization block has no 'sameAs' array.",
                        "Add a 'sameAs' array listing authoritative external profiles "
                        "(Wikidata, LinkedIn company page, Crunchbase, official social "
                        "accounts). This is the explicit machine signal that ties multiple "
                        "independent mentions of the brand back to one entity.",
                        "medium",
                        "sameas-missing",
                        page_url,
                    )
                addr = block.get("address")
                phone = block.get("telephone")
                if addr:
                    addr_str = addr if isinstance(addr, str) else json.dumps(addr)
                    visible = strip_tags(html)
                    # crude check: does at least the postal code / street number show in visible text?
                    tokens = re.findall(r'\d{3,}', addr_str)
                    if tokens and not any(tok in visible for tok in tokens):
                        add(
                            "Address in structured data doesn't appear anywhere in visible page text",
                            "medium",
                            f"{page_url}: structured address contains {tokens} not found in "
                            "rendered text.",
                            "Make sure the same address shown to machines in JSON-LD is also "
                            "present as plain visible text (e.g. in the footer) — consistency "
                            "between the two is itself a trust signal.",
                            "medium",
                            "nap-address-mismatch",
                            page_url,
                        )
                if phone:
                    visible = strip_tags(html)
                    digits_struct = re.sub(r'\D', '', str(phone))
                    visible_numbers = [re.sub(r'\D', '', m.group(1)) for m in PHONE_RE.finditer(visible)]
                    if digits_struct and not any(digits_struct[-7:] == v[-7:] for v in visible_numbers if len(v) >= 7):
                        add(
                            "Phone number in structured data doesn't match any visible phone number",
                            "low",
                            f"{page_url}: structured telephone '{phone}' not matched in visible text.",
                            "Ensure the visible contact phone number and the JSON-LD 'telephone' "
                            "field agree exactly.",
                            "low",
                            "nap-phone-mismatch",
                            page_url,
                        )

            if "Product" in types:
                offers = block.get("offers")
                missing = []
                if not block.get("name"):
                    missing.append("name")
                if not offers:
                    missing.append("offers")
                else:
                    offer_obj = offers[0] if isinstance(offers, list) and offers else offers
                    if isinstance(offer_obj, dict):
                        if not offer_obj.get("price") and not offer_obj.get("lowPrice"):
                            missing.append("offers.price")
                        if not offer_obj.get("priceCurrency"):
                            missing.append("offers.priceCurrency")
                if missing:
                    add(
                        f"Product structured data missing required field(s): {', '.join(missing)}",
                        "high",
                        f"{page_url}: Product block has keys {sorted(block.keys())}",
                        "Populate the missing Product/Offer fields so an assistant can quote "
                        "an exact, current price and availability rather than omitting the "
                        "product or guessing.",
                        "high",
                        "jsonld-missing-required-field",
                        page_url,
                    )
                if not block.get("sku") and not block.get("gtin") and not block.get("mpn"):
                    add(
                        "Product has no stable identifier (sku/gtin/mpn)",
                        "low",
                        f"{page_url}: Product block has no sku, gtin, or mpn.",
                        "Add a stable product identifier so mentions of this product across "
                        "different sources (marketplaces, review sites) can be tied together "
                        "as the same entity.",
                        "low",
                        "product-no-identifier",
                        page_url,
                    )

            # Freshness (Article/BlogPosting or any block carrying date fields)
            date_val = block.get("dateModified") or block.get("datePublished")
            if ("Article" in types or "BlogPosting" in types) and not date_val:
                add(
                    "Article/BlogPosting structured data has no date field",
                    "medium",
                    f"{page_url}: block type {types} has neither dateModified nor datePublished.",
                    "Add datePublished (and update dateModified whenever the content changes) "
                    "so assistants can judge and state how current the information is.",
                    "medium",
                    "freshness-missing-structured",
                    page_url,
                )
            elif date_val:
                dt = parse_date(str(date_val))
                if dt and (now - dt).days > 365:
                    meta_match = MODIFIED_META_RE.search(html)
                    text_match = UPDATED_TEXT_RE.search(strip_tags(html))
                    if not meta_match and not text_match:
                        add(
                            "Content is over a year old with no freshness signal for a reader/crawler",
                            "medium",
                            f"{page_url}: structured date {date_val} is {(now - dt).days} days "
                            "old; no article:modified_time meta tag or visible 'Last updated' "
                            "text found.",
                            "Either refresh the content and update dateModified, or add a "
                            "visible 'Last updated' note confirming it's still accurate. "
                            "Assistants trust dateable facts over stale, unconfirmed ones.",
                            "medium",
                            "stale-content",
                            page_url,
                        )

        # Page-wide: any sameAs values pointing to authoritative domains?
        sameas_matches = SAMEAS_RE.findall(html)
        has_authoritative = any(
            dom in m for m in sameas_matches for dom in AUTHORITATIVE_DOMAINS
        )
        if page_url == url and not has_authoritative and org_like_found:
            pass  # already covered by the per-block sameAs check above

    if not org_like_found:
        add(
            "No Organization/LocalBusiness structured data found anywhere sampled",
            "critical",
            f"Sampled {len(pages)} page(s) starting at {url}; none contain an Organization, "
            "LocalBusiness, or Corporation JSON-LD block.",
            "Add an Organization JSON-LD block (name, url, logo, sameAs, address, telephone) "
            "to the homepage at minimum. Without it, assistants have no authoritative, "
            "machine-readable statement of who the brand even is.",
            "critical",
            "org-entity-missing",
            url,
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
    print(json.dumps({"skill": "entity-corroboration-audit", "findings": findings}))


if __name__ == "__main__":
    main()
