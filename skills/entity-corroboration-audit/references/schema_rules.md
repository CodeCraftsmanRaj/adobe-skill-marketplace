# Structured Data & Corroboration Rules

Reference notes for the entity-corroboration-audit skill.

## Required vs recommended fields (this skill's working definition)

These are intentionally a practical subset of full schema.org, chosen because they're the
fields an assistant most needs to safely extract and quote a fact (per Round-2 appendix
sections B–D: easily-reached, easily-read, easily-quoted facts get used).

**Organization / LocalBusiness**
- Required: `name`, `url`
- Recommended: `logo`, `address`, `telephone`, `sameAs`

**Product**
- Required: `name`, `offers` (containing `price`/`lowPrice` and `priceCurrency`)
- Recommended: `sku`/`gtin`/`mpn`, truthful `aggregateRating`

**Article / BlogPosting**
- Required: `headline`, `datePublished`
- Recommended: `dateModified`, `author`

## Why sameAs matters (appendix D)

A fact repeated identically across several independent, unrelated sources is trusted more than
a fact that lives in exactly one place. `sameAs` is the direct machine-readable expression of
"this profile, on this other trusted platform, is the same entity as this one" — it's how a
generic-sounding brand name avoids being folded together with an unrelated namesake, and how an
assistant can corroborate a claim against a second independent source instead of taking the
brand's own word for it.

## Why freshness needs *both* a structured date and a human-visible one

A `dateModified` field alone helps a machine reading structured data, but many summarization and
citation pipelines work primarily from visible text. A visible "Last updated" line protects
against pipelines that don't parse JSON-LD at all. The audit only flags staleness when *neither*
signal is present — having just one is enough to pass.

## NAP (Name / Address / Phone) consistency

Mismatches between structured data and visible text are a common byproduct of templates that
were updated in one place (e.g. a CMS's structured-data plugin) but not the other (hand-written
footer HTML). Because this is the same underlying fact stated twice, disagreement between the
two versions is itself a negative trust signal — worse in some ways than stating it only once.

## Severity rationale

- **critical** — no Organization-level entity declared anywhere; the assistant has no
  authoritative statement of who the brand even is.
- **high** — required fields missing, or JSON-LD fails to parse at all (functionally equivalent
  to having none, since a parser error usually means the whole block is discarded).
- **medium** — stale content with no freshness signal; missing sameAs; NAP address mismatches.
- **low** — missing recommended-but-not-required fields; minor NAP mismatches (e.g. phone
  formatting); missing product identifiers.
