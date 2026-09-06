# Crawler / Bot Reference Matrix

Reference notes for the crawl-render-audit skill. Not exhaustive, not fetched at runtime —
used to justify the hardcoded `AI_BOTS` list in `scripts/audit_crawl_render.py` and to give a
human reader context when reading a report.

## Named user agents checked

| User agent | Operated by | What it feeds |
|---|---|---|
| `GPTBot` | OpenAI | Model training crawl |
| `ChatGPT-User` | OpenAI | Live browsing done on behalf of a ChatGPT user in-conversation |
| `ClaudeBot` | Anthropic | General crawl |
| `anthropic-ai` | Anthropic | General crawl (legacy token, still checked by many sites) |
| `Claude-Web` | Anthropic | Live browsing on behalf of a Claude user |
| `PerplexityBot` | Perplexity | Answer-engine crawl/citation |
| `Google-Extended` | Google | Controls use in Gemini / AI Overviews, separate from classic Googlebot |
| `CCBot` | Common Crawl | Feeds many downstream LLM training sets |
| `Bytespider` | ByteDance | General crawl, feeds ByteDance AI products |
| `Applebot-Extended` | Apple | Controls use in Apple Intelligence features, separate from classic Applebot |

## Why per-agent matters, not just `*`

A site can leave `User-agent: *` open while specifically blocking one AI agent (or vice versa —
block everything with `*` and forget to allow anything back). The audit checks each named agent
against both its own section and the wildcard fallback, and reports the specific agent(s)
affected so the fix is a one-line robots.txt edit, not a guess.

## Why render-gap detection can't be perfect without a real browser

This skill deliberately does **not** spin up a headless browser (keeps the skill dependency-light,
fast, and safely read-only). Instead it uses a heuristic: very little visible text in the raw
HTML combined with a large inline/external script payload and a near-empty known SPA root
container (`#root`, `#app`, `#__next`, `#___gatsby`, `#__nuxt`). This reliably catches the common
case (a full client-side-rendered SPA) without false-positiving on pages that are simply short.
Borderline pages are reported at `high` (not `critical`) severity precisely because the
heuristic is not a substitute for an actual headless-browser diff, and a human/agent reviewing
the report should spot-check flagged pages before treating the finding as certain.

## Severity rationale

- **critical** — the site or a key path is completely unreachable, or is explicitly blocking a
  named AI bot. Nothing downstream matters until this is fixed.
- **high** — the page loads, but its actual content is very likely invisible to a non-JS reader.
- **medium** — redirect/meta-refresh/canonical issues that add friction or ambiguity but don't
  fully block access.
- **low** — hygiene and emerging-convention items (llms.txt, self-canonical) that are good
  practice but not currently make-or-break for citation.
