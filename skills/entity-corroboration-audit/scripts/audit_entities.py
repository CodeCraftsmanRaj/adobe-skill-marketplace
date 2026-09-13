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
import html as html_module
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

    NON_HTML_EXTENSIONS = (
        ".css", ".js", ".json", ".xml", ".txt",
        ".pdf", ".zip", ".gz",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp3", ".wav", ".mp4", ".webm", ".avi",
    )

    for m in re.finditer(r'href=["\']([^"\'#]+)', html, flags=re.IGNORECASE):
        href = m.group(1)
        href = html_module.unescape(href)

        full = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(full)

        if parsed.netloc != host or parsed.scheme not in ("http", "https"):
            continue

        # Ignore obvious non-HTML resources before fetching.
        if parsed.path.lower().endswith(NON_HTML_EXTENSIONS):
            continue

        if full in seen:
            continue

        seen.add(full)

        # Prefer likely content pages.
        score = 0
        low = full.lower()

        for kw in (
            "docs", "reference", "guide", "article",
            "product", "shop", "pricing", "about",
            "contact", "company",
        ):
            if kw in low:
                score += 1

        links.append((score, full))

        # Collect enough candidates before ranking.
        if len(links) >= limit * 4:
            break

    links.sort(key=lambda item: -item[0])

    return [url for _, url in links[:limit]]

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


def normalize_fact(value):
    """Normalize simple entity facts before comparison."""
    if value is None:
        return ""

    if isinstance(value, dict):
        # Useful for schema.org PostalAddress
        parts = []
        for key in (
            "streetAddress",
            "addressLocality",
            "addressRegion",
            "postalCode",
            "addressCountry",
        ):
            if value.get(key):
                parts.append(str(value[key]))
        value = " ".join(parts)

    value = html_module.unescape(str(value)).strip().lower()
    # Normalize whitespace
    value = re.sub(r"\s*\(@[^)]*\)", "", value)
    # Normalize URLs
    if value.startswith(("http://", "https://")):
        value = value.rstrip("/")
        value = re.sub(r"^https?://(www\.)?", "", value)

    # Normalize phone numbers
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7:
        return digits

    return value


def fetch_corroboration(url, headers, timeout):
    """Fetch one public corroboration source using read-only GET."""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return None, "unsupported scheme"

    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )

        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}"

        content_type = resp.headers.get("Content-Type", "").lower()

        if not any(t in content_type for t in ("text/html", "application/json")):
            return None, f"unsupported content type: {content_type}"

        return resp, None

    except requests.RequestException as exc:
        return None, str(exc)
    


def extract_corroboration_facts(html):
    """Extract simple identity facts from an external HTML page."""
    facts = {}

    blocks = load_jsonld_blocks(html)

    for block in blocks:
        types = get_type(block)

        if any(
            t in ("Organization", "Corporation", "LocalBusiness", "Brand", "Product")
            for t in types
        ):
            for field in ("name", "url", "telephone", "sku", "gtin", "mpn"):
                if block.get(field):
                    facts[field] = normalize_fact(block[field])

            if block.get("brand"):
                brand = block["brand"]
                if isinstance(brand, dict):
                    brand = brand.get("name")
                if brand:
                    facts["brand"] = normalize_fact(brand)

            if block.get("address"):
                facts["address"] = normalize_fact(block["address"])

            offers = block.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None

            if isinstance(offers, dict):
                for field in ("price", "priceCurrency", "availability"):
                    if offers.get(field):
                        facts[field] = normalize_fact(offers[field])

            if facts:
                return facts

    # Fallback: use visible page title if no structured entity was found.
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if title_match:
        title = strip_tags(title_match.group(1))

    # Social/profile page titles often contain extra UI text.
    # Extract the actual profile name instead of treating the full
    # browser title as the entity name.
    title = re.split(
        r"\s*(?:\||•|-)\s*(?:instagram|facebook|twitter|x|linkedin|photos|videos|official).*",
        title,
        flags=re.IGNORECASE,
    )[0]

    title = title.strip()

    if title:
        facts["name"] = normalize_fact(title)

    return facts



def compare_entity_facts(website_facts, external_facts):
    """Return fields that exist in both sources but disagree."""
    conflicts = []

    for field in (
        "name",
        "url",
        "telephone",
        "address",
        "brand",
        "sku",
        "gtin",
        "mpn",
        "price",
        "priceCurrency",
        "availability",
    ):
        website_value = website_facts.get(field)
        external_value = external_facts.get(field)

        if not website_value or not external_value:
            continue

        if normalize_fact(website_value) != normalize_fact(external_value):
            conflicts.append(
                {
                    "field": field,
                    "website": website_value,
                    "external": external_value,
                }
            )

    return conflicts



def classify_page_type(page_url: str, html: str, is_homepage: bool) -> str:
    """
    Classify the page only when there is enough evidence to expect
    page-specific structured data.
    """
    if is_homepage:
        return "homepage"

    low_url = page_url.lower()

    # Product/commercial pages
    if any(term in low_url for term in (
        "/product", "/products/", "/shop/", "/store/",
        "/item/", "/p/", "/dp/"
    )):
        return "product"

    # Article/blog/news pages
    if any(term in low_url for term in (
        "/blog/", "/article/", "/articles/", "/news/",
        "/stories/", "/posts/"
    )):
        return "article"

    # Documentation/reference pages do not inherently require JSON-LD.
    if any(term in low_url for term in (
        "/docs/", "/documentation/", "/reference/",
        "/guide/", "/guides/", "/developer/"
    )):
        return "documentation"

    # Look for strong HTML hints for articles.
    if re.search(
        r'<(?:article|main)[^>]*class=["\'][^"\']*'
        r'(?:article|blog|post|news)[^"\']*["\']',
        html,
        re.IGNORECASE,
    ):
        return "article"

    return "generic"


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
        if r is not None and err is None and r.status_code < 400 and "html" in r.headers.get("Content-Type", "").lower():
            pages.append((link, r.text))

    now = datetime.now(timezone.utc)
    org_like_found = False
    brand_name_guess = None
    corroboration_attempts = 0
    max_corroboration_sources = 2

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

        page_type = classify_page_type(
            page_url,
            html,
            is_homepage=(page_url == url),
        )

        if not real_blocks:
            if page_type == "homepage":
                add(
                    "No valid JSON-LD structured data found on homepage",
                    "high",
                    f"{page_url}: homepage has 0 parsable "
                    '<script type="application/ld+json"> blocks.',
                    "Add Organization JSON-LD to the homepage so assistants can "
                    "identify the brand and its authoritative identity.",
                    "high",
                    "jsonld-missing",
                    page_url,
                )

            elif page_type == "product":
                add(
                    "No Product structured data found on product page",
                    "high",
                    f"{page_url}: product-like page has 0 parsable "
                    '<script type="application/ld+json"> blocks.',
                    "Add Product JSON-LD with the product name and relevant Offer "
                    "information so assistants can extract exact product facts.",
                    "high",
                    "jsonld-missing-product",
                    page_url,
                )

            elif page_type == "article":
                add(
                    "No Article structured data found on article page",
                    "high",
                    f"{page_url}: article-like page has 0 parsable "
                    '<script type="application/ld+json"> blocks.',
                    "Add Article or BlogPosting JSON-LD with author and publication "
                    "or modification dates so assistants can identify and assess "
                    "the content.",
                    "high",
                    "jsonld-missing-article",
                    page_url,
                )
                # Documentation and generic pages do not get a missing-JSON-LD finding.
            continue

        for block in real_blocks:
            types = get_type(block)

            if any(t in ("Organization", "LocalBusiness", "Corporation") for t in types):
                org_like_found = True
                brand_name_guess = brand_name_guess or block.get("name")
                                # External corroboration through sameAs links.
                same_as = block.get("sameAs", [])

                if isinstance(same_as, str):
                    same_as = [same_as]

                if isinstance(same_as, list):
                    for external_url in same_as:
                        if corroboration_attempts >= max_corroboration_sources:
                            break

                        if not isinstance(external_url, str):
                            continue

                        if not any(
                            domain in external_url.lower()
                            for domain in AUTHORITATIVE_DOMAINS
                        ):
                            continue

                        corroboration_attempts += 1

                        external_resp, external_err = fetch_corroboration(
                            external_url,
                            headers,
                            timeout,
                        )

                        if external_err or external_resp is None:
                            continue

                        external_facts = extract_corroboration_facts(
                            external_resp.text
                        )

                        website_facts = {
                            "name": block.get("name"),
                            "url": block.get("url"),
                            "telephone": block.get("telephone"),
                            "address": block.get("address"),
                        }

                        conflicts = compare_entity_facts(
                            website_facts,
                            external_facts,
                        )

                        if conflicts:
                            details = "; ".join(
                                f"{c['field']}: website={c['website']!r}, "
                                f"external={c['external']!r}"
                                for c in conflicts
                            )

                            add(
                                "Entity facts conflict with an external corroboration source",
                                "high",
                                f"{page_url}: compared against {external_url}. "
                                f"Conflicts: {details}",
                                "Review the conflicting entity facts and make the "
                                "website's structured data consistent with the "
                                "authoritative external source.",
                                "high",
                                "external-corroboration-conflict",
                                page_url,
                            )
                        else:
                            add(
                                "Entity identity corroborated by an external source",
                                "low",
                                f"{page_url}: entity facts were compared with "
                                f"{external_url}; no conflicting shared identity "
                                "fields were found.",
                                "No action required. Keep the website identity "
                                "facts synchronized with the corroborating source.",
                                "low",
                                "external-corroboration-success",
                                page_url,
                            )
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
            # if addr:
            #     addr_str = addr if isinstance(addr, str) else json.dumps(addr)
            #     visible = strip_tags(html)

            #     # Only flag an address mismatch when a meaningful address component
            #     # is present in structured data but absent from visible page text.
            #     address_parts = []

            #     if isinstance(addr, dict):
            #         for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode"):
            #             value = addr.get(key)
            #             if value:
            #                 address_parts.append(str(value))
            #     else:
            #         address_parts.append(str(addr))

            #     normalized_visible = re.sub(r"\s+", " ", visible).lower()

            #     # Check the strongest/most meaningful components first.
            #     meaningful_parts = [
            #         part.strip()
            #         for part in address_parts
            #         if len(part.strip()) >= 4
            #     ]

            #     matched = any(
            #         re.sub(r"\s+", " ", part).lower() in normalized_visible
            #         for part in meaningful_parts
            #     )

            #     if meaningful_parts and not matched:
            #         add(
            #             "Address in structured data doesn't appear anywhere in visible page text",
            #             "medium",
            #             f"{page_url}: structured address '{addr_str}' was not found in rendered text.",
            #             "Make sure the same address shown to machines in JSON-LD is also "
            #             "present as plain visible text (e.g. in the footer) when appropriate.",
            #             "medium",
            #             "nap-address-mismatch",
            #             page_url,
            #         )
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
