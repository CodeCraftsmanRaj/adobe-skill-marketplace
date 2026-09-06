# Content Extractability Checklist

Reference notes for the content-extractability-audit skill.

## The core distinction this skill draws

A page can be perfectly *reachable* (crawl-render-audit passes) and *structured* (some JSON-LD
present) and still fail the person's actual question, if the specific fact they want is encoded
in a form a text extractor can't read. This skill is about the medium the fact is stored in, not
whether the page exists or is tagged.

## Why each check exists

- **Text-to-markup ratio + heavy media** — a rough proxy for "this page is communicating mostly
  through pictures." Not a defect by itself (a lookbook/gallery page is allowed to be
  image-heavy), which is why it's only `medium` and requires both a low ratio *and* a high media
  count before firing.
- **Price-like pattern only in `alt` text** — the sharpest signal in this skill. If a currency
  amount shows up in an image's alt text but nowhere in the surrounding plain text, that's
  strong evidence the number itself is baked into a picture (e.g. a "SALE $49" banner image)
  and not present anywhere a text extractor can read it independent of OCR.
- **Video without captions/transcript** — mirrors appendix section C directly: a claim narrated
  only in a video is invisible to anything that isn't watching (and transcribing) the video.
- **Canvas** — flagged unconditionally when present, because `<canvas>` is *by construction* a
  bitmap with zero DOM text; there is no heuristic needed, only a judgment call on whether it's
  carrying real content (left to the reader/agent) vs. decoration.
- **SVG with data-like `<text>`** — SVG *can* carry real, selectable text nodes, so it's less
  severe than canvas, but extraction support for SVG text varies by tool, so data-bearing SVG
  (charts, spec diagrams) still gets a low-severity nudge to duplicate the data as HTML.
- **PDF-only spec sheets** — PDFs are not inherently bad (many are perfectly text-extractable),
  but this check flags the *pattern* of "the only place this fact lives is behind a PDF link"
  as a fragility risk, not a certain failure.
- **Heading structure** — supports extraction quality indirectly: a clean H1 → H2 → H3 outline
  helps a summarizer correctly attribute which paragraph of text answers which sub-question.

## Severity rationale

- **high** — a specific, valuable fact (price) is demonstrably only present in a non-text form.
- **medium** — heavy reliance on media generally, or video with no transcript path at all.
- **low** — alt-text coverage, canvas/SVG presence as a general nudge, PDF-only pattern,
  heading-structure hygiene. These are "worth fixing" signals, not proven failures — several are
  heuristics that can have false positives, which the orchestrator's severity-based sort
  reflects by ranking them below confirmed access/entity problems.
