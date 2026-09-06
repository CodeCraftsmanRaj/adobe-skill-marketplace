# Intent Retention Rubric

Reference notes for the engagement-continuity-audit skill.

## The framing: arrival with no context

A visitor who clicks a link inside an AI assistant's answer arrives with essentially none of
the surrounding conversational context available to the page itself — no referrer query string
carrying their original question, often no scroll position beyond a URL fragment. The page has
exactly one shot to (a) confirm they're in the right place, (b) not actively block them from
seeing content, and (c) tell them what to do next. Every check in this skill maps to one of
those three jobs.

| Job | Checks |
|---|---|
| Confirm they're in the right place | anchor integrity, text-scent match, title/H1 presence |
| Don't block them from seeing content | interstitial/modal detection, mobile viewport |
| Tell them what to do next | CTA presence |

## Why "text scent" is measured against the page's own body, not a fixed keyword list

There's no universal "correct" meta description — the only meaningful check is internal
consistency: does what the page *promises* (title, description) match what it *delivers* (body
text)? A low keyword-overlap score is a proxy for a visitor's actual experience of "this isn't
what I expected," which is one of the best-documented predictors of an immediate bounce.

## Why modal/interstitial detection is a "suspected" finding, not a certain one

This skill inspects only the initial server-rendered HTML (consistent with crawl-render-audit's
approach — no headless browser). A `modal`/`overlay`-named element with fixed positioning in the
markup is strong circumstantial evidence it fires on load, but confirming it definitely blocks
the viewport (vs., say, a dismissed default state or a class name reused for something benign)
would need a rendered screenshot diff. The finding is deliberately worded as "suggests" /
"suspected" and capped at `medium` severity, with a suggested next step of manual/headless
confirmation — the skill would rather flag a false positive for a human to dismiss quickly than
silently miss a real blocking overlay.

## Severity rationale

- **high** — no orientation heading at all (neither title nor H1); a visitor genuinely cannot
  tell what the page is.
- **medium** — broken anchors, text-scent mismatch, suspected blocking interstitial, missing
  viewport, missing CTA — each independently plausible as a bounce cause.
- **low** — missing meta description, misconfigured (but present) viewport — hygiene issues that
  weaken but don't independently sink the visit.
