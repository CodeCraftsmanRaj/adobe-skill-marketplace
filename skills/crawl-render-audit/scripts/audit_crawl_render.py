#!/usr/bin/env python3
"""
crawl-render-audit / audit_crawl_render.py

Read-only checks for: AI-bot robots.txt access, llms.txt presence, SSR-vs-CSR render gaps,
canonical hygiene, and redirect/meta-refresh chains.

Usage:
    python3 audit_crawl_render.py --url https://example.com [--max-pages 8] [--timeout 10] \
        [--user-agent "MyBot/1.0"]

Prints: {"skill": "crawl-render-audit", "findings": [...]}
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    print(json.dumps({"skill": "crawl-render-audit", "findings": [{
        "id": "CR-000", "title": "Missing dependency: requests", "severity": "low",
        "evidence": "The 'requests' package is not installed in this environment.",
        "suggested_action": {"summary": "pip install requests", "priority": "low"},
    }]}))
    sys.exit(0)

AI_BOTS = [
    "GPTBot", "ChatGPT-User", "ClaudeBot", "anthropic-ai", "Claude-Web",
    "PerplexityBot", "Google-Extended", "CCBot", "Bytespider", "Applebot-Extended",
]

SPA_ROOT_IDS = ("root", "app", "__next", "___gatsby", "__nuxt")


class SimpleTextExtractor(HTMLParser):
    """Extracts visible text (ignoring script/style/noscript) and collects basic structural
    signals without needing a full DOM / JS-execution engine."""

    def __init__(self):
        super().__init__()
        self.in_skip = 0
        self.text_parts = []
        self.script_bytes = 0
        self.spa_root_near_empty = False
        self.canonical_hrefs = []
        self.meta_refresh = None
        self._cur_tag_stack = []
        self._root_div_depth = None
        self._root_div_text_len = 0

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.in_skip += 1
        if tag == "link" and attrs_d.get("rel", "").lower() == "canonical" and attrs_d.get("href"):
            self.canonical_hrefs.append(attrs_d["href"])
        if tag == "meta" and attrs_d.get("http-equiv", "").lower() == "refresh":
            self.meta_refresh = attrs_d.get("content", "")
        if tag == "div":
            elid = attrs_d.get("id", "")
            if elid in SPA_ROOT_IDS and self._root_div_depth is None:
                self._root_div_depth = len(self._cur_tag_stack)
        self._cur_tag_stack.append(tag)

    def handle_endtag(self, tag):
        if self._cur_tag_stack and self._cur_tag_stack[-1] == tag:
            self._cur_tag_stack.pop()
        if tag in ("script", "style", "noscript") and self.in_skip > 0:
            self.in_skip -= 1
        if tag == "div" and self._root_div_depth is not None and len(self._cur_tag_stack) <= self._root_div_depth:
            self._root_div_depth = None  # closed; stop tracking

    def handle_data(self, data):
        if self.in_skip:
            self.script_bytes += len(data)
            return
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)
            if self._root_div_depth is not None:
                self._root_div_text_len += len(stripped)

    def visible_text(self) -> str:
        return " ".join(self.text_parts)


def fetch(url, headers, timeout):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        return resp, None
    except requests.RequestException as exc:
        return None, str(exc)


def parse_robots(text: str) -> dict:
    """Very small robots.txt parser: returns {user-agent-lower: [disallow paths]}."""
    rules = {}
    current_agents = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current_agents and current_agents[-1] in rules and rules[current_agents[-1]] == []:
                pass
            current_agents = [value.lower()]
            for a in current_agents:
                rules.setdefault(a, [])
        elif key == "disallow" and current_agents:
            for a in current_agents:
                rules.setdefault(a, []).append(value)
    return rules


def agent_is_blocked(rules: dict, agent: str, path: str = "/") -> bool:
    agent_l = agent.lower()
    applicable = rules.get(agent_l)
    if applicable is None:
        applicable = rules.get("*", [])
    for pattern in applicable:
        if pattern == "":
            continue
        if pattern == "/" or path.startswith(pattern):
            return True
    return False


def extract_links(html: str, base_url: str, host: str, limit: int):
    links = set()
    for m in re.finditer(r'href=["\']([^"\'#]+)', html, flags=re.IGNORECASE):
        href = m.group(1)
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.netloc == host and parsed.scheme in ("http", "https"):
            links.add(full.split("#")[0])
        if len(links) >= limit:
            break
    return list(links)


def run_audit(url: str, max_pages: int, timeout: int, user_agent: str) -> list:
    findings = []
    fid = 1

    def add(title, severity, evidence, action_summary, action_priority, check_type, page_url=""):
        nonlocal fid
        findings.append({
            "id": f"CR-{fid:03d}",
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

    # 1. robots.txt
    robots_url = urljoin(origin, "/robots.txt")
    robots_resp, robots_err = fetch(robots_url, headers, timeout)
    if robots_err or robots_resp is None or robots_resp.status_code >= 400:
        add(
            "robots.txt is missing or unreachable",
            "medium",
            f"GET {robots_url} -> {'error: ' + robots_err if robots_err else robots_resp.status_code}",
            "Publish a robots.txt at the domain root. Its absence isn't fatal, but it removes "
            "your only explicit channel for telling AI crawlers what they may access, forcing "
            "them to fall back to default (sometimes overly conservative) behavior.",
            "medium",
            "robots-missing",
            robots_url,
        )
        rules = {}
    else:
        rules = parse_robots(robots_resp.text)
        blocked = [a for a in AI_BOTS if agent_is_blocked(rules, a, parsed.path or "/")]
        if blocked:
            add(
                f"robots.txt blocks {len(blocked)} AI-assistant crawler(s) from key content",
                "critical",
                f"robots.txt at {robots_url} disallows: {', '.join(blocked)} from "
                f"'{parsed.path or '/'}' (via explicit rule or unscoped '*' Disallow).",
                "Add explicit Allow rules (or remove the blocking Disallow) for the named AI "
                "user agents on public marketing/product pages. A blocked bot cannot cite the "
                "brand at all, regardless of how good the content is.",
                "critical",
                "robots-ai-bot-block",
                robots_url,
            )

    # 2. llms.txt
    llms_url = urljoin(origin, "/llms.txt")
    llms_resp, llms_err = fetch(llms_url, headers, timeout)
    if llms_err or llms_resp is None or llms_resp.status_code >= 400:
        add(
            "No llms.txt found",
            "low",
            f"GET {llms_url} -> {'error: ' + llms_err if llms_err else llms_resp.status_code}",
            "Consider publishing an llms.txt at the domain root: a short, curated markdown "
            "index of the pages you most want an LLM to read (company facts, product specs, "
            "pricing, docs). This is an emerging, optional convention, not a defect.",
            "low",
            "llms-txt-missing",
            llms_url,
        )
    else:
        body = llms_resp.text
        if "#" not in body or "[" not in body:
            add(
                "llms.txt exists but doesn't follow the curated markdown-index convention",
                "low",
                f"{llms_url} returned {len(body)} bytes with no markdown heading ('#') and/or "
                "no links ('[...]').",
                "Structure llms.txt as a short markdown document: an H1 with the brand name, a "
                "one-paragraph summary, then a list of links to the pages an LLM should "
                "prioritize reading.",
                "low",
                "llms-txt-malformed",
                llms_url,
            )

    # 3. Fetch homepage + sample internal links
    home_resp, home_err = fetch(url, headers, timeout)
    if home_err or home_resp is None:
        add(
            "Homepage is unreachable to a plain HTTP client",
            "critical",
            f"GET {url} -> error: {home_err}",
            "Investigate hosting/CDN/WAF configuration — if a simple HTTP client can't fetch "
            "the page, most crawlers (including AI-assistant fetchers) will fail identically.",
            "critical",
            "fetch-error",
            url,
        )
        return findings

    if home_resp.status_code >= 400:
        add(
            f"Homepage returns HTTP {home_resp.status_code}",
            "critical",
            f"GET {url} -> {home_resp.status_code}",
            "Fix the server error / access issue at the source; an error status here means "
            "essentially nothing on the site will be crawlable.",
            "critical",
            "fetch-error",
            url,
        )
        return findings

    pages_to_check = [(url, home_resp)]
    links = extract_links(home_resp.text, url, host, limit=max_pages * 3)
    sampled = 0
    for link in links:
        if sampled >= max_pages:
            break
        resp, err = fetch(link, headers, timeout)
        if resp is not None and err is None:
            pages_to_check.append((link, resp))
            sampled += 1

    # 4-6. Per-page checks
    redirect_hop_flagged = set()
    for page_url, resp in pages_to_check:
        # Redirect chain length
        if len(resp.history) >= 3:
            chain = " -> ".join([r.url for r in resp.history] + [resp.url])
            add(
                f"Long redirect chain ({len(resp.history)} hops) before reaching content",
                "medium",
                f"{page_url}: {chain}",
                "Collapse the chain to a single 301/302 redirect straight to the final URL. "
                "Long chains cost crawl budget and some simple fetchers give up before the end.",
                "medium",
                "redirect-chain",
                page_url,
            )

        parser = SimpleTextExtractor()
        try:
            parser.feed(resp.text)
        except Exception:
            continue

        if parser.meta_refresh and "url=" in parser.meta_refresh.lower():
            add(
                "Page uses a client-side meta-refresh instead of a proper HTTP redirect",
                "medium",
                f"{page_url}: <meta http-equiv=\"refresh\" content=\"{parser.meta_refresh}\">",
                "Replace the meta-refresh with a server-side 301/302 HTTP redirect so crawlers "
                "that don't execute page-level meta tags still land on the right content.",
                "medium",
                "meta-refresh",
                page_url,
            )

        visible_text = parser.visible_text()
        visible_len = len(visible_text)
        if visible_len < 150 and parser.script_bytes > 2000:
            spa_note = (" A near-empty SPA root container was also detected."
                        if parser._root_div_text_len < 50 and parser._root_div_depth is None
                        and parser.script_bytes > 0 else "")
            add(
                "Meaningful content is likely assembled client-side and invisible to non-JS crawlers",
                "high",
                f"{page_url}: only {visible_len} chars of visible text in raw HTML vs "
                f"{parser.script_bytes} bytes inside <script> tags.{spa_note}",
                "Server-side render (SSR) or statically pre-render the primary content — "
                "product facts, pricing, specs, key copy — so it's present in the initial "
                "HTML response before any JavaScript runs. Reserve client-side JS for "
                "interactivity, not for first-paint of essential facts.",
                "high",
                "render-gap",
                page_url,
            )

        if not parser.canonical_hrefs:
            add(
                "Missing canonical tag",
                "low",
                f"{page_url}: no <link rel=\"canonical\"> found.",
                "Add a self-referencing canonical tag to every indexable page to avoid "
                "duplicate-content ambiguity for crawlers and citation systems.",
                "low",
                "canonical-missing",
                page_url,
            )
        elif len(set(parser.canonical_hrefs)) > 1:
            add(
                "Multiple conflicting canonical tags",
                "medium",
                f"{page_url}: found canonical hrefs {parser.canonical_hrefs}",
                "Emit exactly one canonical link per page; conflicting canonicals leave "
                "crawlers to guess which URL is authoritative.",
                "medium",
                "canonical-conflict",
                page_url,
            )
        else:
            canon = urljoin(page_url, parser.canonical_hrefs[0])
            if urlparse(canon).path.rstrip("/") not in (urlparse(page_url).path.rstrip("/"), ""):
                add(
                    "Canonical tag points to a different page without obvious reason",
                    "low",
                    f"{page_url}: canonical points to {canon}",
                    "Verify this is intentional (e.g. a tracked/parameterized URL canonicalizing "
                    "to its clean form). If not, point the canonical at the page itself.",
                    "low",
                    "canonical-mismatch",
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
    print(json.dumps({"skill": "crawl-render-audit", "findings": findings}))


if __name__ == "__main__":
    main()
