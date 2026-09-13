# Website Audit Results

## 1. Example.com

**Command:**
`uv run python skills/audit-orchestrator/scripts/orchestrate.py --url "https://example.com" --max-pages 5`

**Audited at:** 2026-09-13T18:28:57Z

  Metric                       Result
  -------------------- --------------
  Total findings                    6
  Critical                          1
  High                              1
  Medium                            1
  Low                               3
  AI readiness score               56
  Runtime                2.52 seconds

### Findings

-   **F-001 --- No Organization/LocalBusiness structured data found**
    --- Critical. No Organization, LocalBusiness, or Corporation JSON-LD
    block was found in the sampled page. **Action:** Add Organization
    JSON-LD with name, URL, logo, sameAs, address, and telephone.
-   **F-002 --- No valid JSON-LD structured data found** --- High. 0
    parsable `application/ld+json` blocks. **Action:** Add appropriate
    schema.org JSON-LD.
-   **F-003 --- robots.txt is missing or unreachable** --- Medium.
    `https://example.com/robots.txt` returned 404. **Action:** Publish
    robots.txt at the domain root.
-   **F-004 --- No llms.txt found** --- Low.
    `https://example.com/llms.txt` returned 404. **Action:** Consider
    publishing llms.txt.
-   **F-005 --- Missing canonical tag** --- Low. No canonical tag was
    found. **Action:** Add a self-referencing canonical tag to indexable
    pages.
-   **F-006 --- Missing meta description** --- Low. No meta description
    was found. **Action:** Add a concise, accurate meta description.

------------------------------------------------------------------------

## 2. Adobe.com

**Command:**
`uv run python skills/audit-orchestrator/scripts/orchestrate.py --url https://www.adobe.com --max-pages 3 --timeout 5`

**Audited at:** 2026-09-13T18:29:12Z

  Metric                       Result
  -------------------- --------------
  Total findings                    8
  Critical                          0
  High                              2
  Medium                            3
  Low                               3
  AI readiness score               52
  Runtime                6.04 seconds

### Findings

-   **F-001 --- No valid JSON-LD structured data found** --- High.
    `https://www.adobe.com/products/firefly.html` had 0 parsable JSON-LD
    blocks. **Action:** Add appropriate schema.org JSON-LD.
-   **F-002 --- No valid JSON-LD structured data found** --- High. The
    sampled Adobe fragment URL had 0 parsable JSON-LD blocks.
    **Action:** Add appropriate schema.org JSON-LD.
-   **F-003 --- Address in structured data doesn't appear in visible
    page text** --- Medium. Structured address contains `345` and
    `95110`, not found in rendered text. **Action:** Ensure the same
    address is visible as text.
-   **F-004 --- No clear call-to-action text found** --- Medium. Common
    CTA phrases were not found on the Adobe homepage. **Action:** Add an
    explicit next step near the top.
-   **F-005 --- No clear call-to-action text found** --- Medium. Common
    CTA phrases were not found on the sampled fragment. **Action:** Add
    an explicit next step.
-   **F-006 --- Low meaningful alt-text coverage** --- Low. 5/11 images
    had descriptive alt text (45%). **Action:** Improve alt text for
    content-bearing images.
-   **F-007 --- Low meaningful alt-text coverage** --- Low. 4/10 images
    had descriptive alt text (40%) on the Firefly page. **Action:**
    Improve alt text.
-   **F-008 --- Page has no `<h1>`** --- Low. The sampled fragment had 0
    headings. **Action:** Add exactly one `<h1>` describing the page's
    primary subject.

------------------------------------------------------------------------

## 3. Mozilla.org

**Command:**
`uv run python skills/audit-orchestrator/scripts/orchestrate.py --url https://www.mozilla.org --max-pages 3 --timeout 5`

**Audited at:** 2026-09-13T18:29:24Z

  Metric                       Result
  -------------------- --------------
  Total findings                   10
  Critical                          1
  High                              3
  Medium                            2
  Low                               4
  AI readiness score               24
  Runtime                8.79 seconds

### Findings

-   **F-001 --- No Organization/LocalBusiness structured data found**
    --- Critical. Four sampled pages contained no Organization,
    LocalBusiness, or Corporation JSON-LD. **Action:** Add Organization
    JSON-LD to the homepage at minimum.
-   **F-002 --- No valid JSON-LD structured data found** --- High.
    `https://www.mozilla.org` had 0 parsable JSON-LD blocks.
-   **F-003 --- No valid JSON-LD structured data found** --- High.
    `https://www.mozilla.org/ach` had 0 parsable JSON-LD blocks.
-   **F-004 --- No valid JSON-LD structured data found** --- High.
    `https://www.mozilla.org/ar` had 0 parsable JSON-LD blocks.
-   **F-005 --- Very low text-to-markup ratio alongside heavy media
    use** --- Medium. Visible text was 4.9% of page size, with 13
    images, 0 videos, 0 canvas elements, and 3 inline SVGs. **Action:**
    Ensure important facts are available as plain text.
-   **F-006 --- No clear call-to-action text found** --- Medium. Common
    CTA phrases were not found on `/ar`. **Action:** Add an explicit
    next step.
-   **F-007 --- No llms.txt found** --- Low.
    `https://www.mozilla.org/llms.txt` returned 404. **Action:**
    Consider publishing llms.txt.
-   **F-008 --- Missing canonical tag** --- Low. No canonical tag was
    found on the homepage. **Action:** Add a self-referencing canonical
    tag where appropriate.
-   **F-009 --- Canonical tag points to a different page** --- Low.
    `/ach` canonicalizes to `/en-US/`. **Action:** Verify this is
    intentional.
-   **F-010 --- Low meaningful alt-text coverage** --- Low. 2/13 images
    had descriptive alt text (15%). **Action:** Improve alt text.

------------------------------------------------------------------------

## 4. End-to-End Output File Test

**Command:**
`uv run python skills/audit-orchestrator/scripts/orchestrate.py --url https://example.com --max-pages 3 --timeout 5 --out example-report.json`

The command completed successfully and generated the report.

  Metric                       Result
  -------------------- --------------
  Total findings                    6
  Critical                          1
  High                              1
  Medium                            1
  Low                               3
  AI readiness score               56
  Runtime                2.81 seconds

------------------------------------------------------------------------

## Overall Comparison

  Website             Findings   Critical   High   Medium   Low   AI Readiness
  ----------------- ---------- ---------- ------ -------- ----- --------------
  example.com                6          1      1        1     3             56
  www.adobe.com              8          0      2        3     3             52
  www.mozilla.org           10          1      3        2     4             24

### Key Observations

1.  Example.com had the highest AI readiness score in this test set:
    **56**.
2.  Adobe.com scored **52**, with no critical findings in this sampled
    run.
3.  Mozilla.org scored **24**, with one critical and three high-severity
    findings.
4.  The orchestrator completed all three website audits without a
    traceback.
5.  The output-file test completed successfully.

> These results reflect the pages and crawl limits used in the recorded
> commands and are not a complete audit of the entire websites.
