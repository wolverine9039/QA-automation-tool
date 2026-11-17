# Design: resolve "check manually" links + cleaner CSV exports

(The full architecture plan lives in `docs/ARCHITECTURE_PLAN.md`; this file covers this change only.)

## Context
- **The problem.** On a real page (Hybrid Workspaces) the dashboard shows **Broken: 0**, while 6 links sit in "check manually". The community.opentext.com links are behind Imperva and blogs.opentext.com is behind Cloudflare. A QA reviewer reads "0 broken" as all clear even though those links were never checked.
- **What they want instead.** They want those links resolved, so they are counted as working or broken.
- **Exports.** The exported CSV is hard to read: cramped columns, developer column names, and no page context.

**Constraint.** The tool must not try to defeat bot protection (no stealth flags or fingerprint spoofing). A test of that was blocked, correctly. The two legitimate routes are a human check in the dashboard and a client-side allowlist.

## Approaches considered
| Approach | Trade-off | Decision |
|---|---|---|
| Human check in dashboard | Works today, no client dependency; costs the reviewer a few clicks per blocked link | **Picked** |
| WAF allowlist header | Fully automatic, but only after OpenText's web team configures Cloudflare/Imperva | **Picked**, alongside the above |
| Bypass bot protection automatically | Evades security controls | Rejected |
| Excel export | Best formatting | User chose CSV only |

## Design

### 1. Human check in the dashboard
- A highlighted block, **"N links need a human check"**, sits above the findings. Each row has the link text and URL, an **Open link** button (new tab), and **Works ✓** / **Broken ✗** buttons.
- Each button posts to `POST /runs/{id}/review` with `url` and `verdict`, then returns a 303 redirect back to `/runs/{id}#review`. These are plain HTML forms with no JS dependency.
- The new helper `engine.runner.apply_review(result, url, verdict, cfg)`:
  - sets the `CheckResult` outcome to `ok`/`broken` and `checked_by="reviewer"`;
  - marks a broken link with the error "Marked broken by reviewer";
  - recomputes the findings with the existing `evaluate()` (`engine/rules/link/broken_links.py`) and the inventory with `summarize()` (`engine/inventory.py`), using the same sorting as `run()`.

  So counters, findings and CSVs update with no new rule code.
- **Validation (trust boundary):** `verdict ∈ {ok, broken}`, and the `url` must be a result of that run that was unverifiable or already reviewed. Anything else gets a 400.
- A reviewer can change a verdict, and it can be undone back to "check manually" with a **reset** verdict.
- The counters read **Broken N · M still to check**, so 0 is never shown as all clear while links are unchecked.

### 2. Allowlist header (automatic once OpenText sets it up)
- **`rules.yaml`:**
  - `allowlist_header: ""` holds the header name, e.g. `X-OT-QA-Tool`;
  - `allowlist_hosts: [opentext.com]` lists the hosts that receive it (subdomains included).
  - The **value** comes from the env var `QA_TOOL_ALLOWLIST_TOKEN`, never from the committed file.
- In the link checker, `_request` adds the header **only** when the URL host is in `allowlist_hosts`, so the token is never sent to third-party sites. If the name or the token is unset, nothing changes.
- The README gets a short paragraph on what to ask OpenText's web team for.

### 3. Cleaner CSV exports (`report/export.py`)
The **findings CSV** starts with a short summary block:

```
QA report,<ticket>
Page,<url>
Checked,<date time>
Totals,"69 links · 0 broken · 2 redirected · 6 to check by hand"
Warnings,<if any>
<blank line>
```

The table follows, with plain-English columns:

**Severity · Action · Issue · Link text · Link on page · Suggested fix · HTTP status · Redirect path · Checked by · Section · Rule**

- Severity is capitalised (Critical, Major…).
- Action is "Fix", "Check by hand", or "Review".
- The redirect path is one hop per line ("url (301)" lines), which shows as line breaks when the CSV is opened in Excel.
- The noisy `Selector` and duplicate resolved-URL columns are dropped.

The **links CSV** gets readable column names and values ("Working", "Broken", "Redirect", "Check by hand", "Not checked"), and keeps every link.

The existing formula-injection guard and the UTF-8 BOM are kept.

### Non-goals
- Any automatic bypass of bot protection.
- Excel output.
- Persisting reviewer verdicts across restarts (runs are still held in memory, max 50, until the SQLite slice).

## Files
- `engine/models.py`: add `CheckResult.checked_by` ("tool" | "reviewer").
- `engine/runner.py`: add `apply_review()`; share the sorting with `run()`.
- `engine/http/link_checker.py`: add the allowlist header, restricted to the configured hosts.
- `governance/rules.yaml`: add `allowlist_header`, `allowlist_hosts`.
- `app/main.py`: add the `POST /runs/{id}/review` route.
- `app/templates/report.html`, `app/static/style.css`: the human-check block and counter wording.
- `report/export.py`: the summary block, plain-English columns, and multi-line redirect path.
- `tests/`: `test_link_checker.py` (header sent only to allowlisted hosts; a `/needs-header` route returns 403 without it), `test_runner.py` (`apply_review` updates findings and inventory), `test_app.py` (review route, 400 on bad input), `test_runner.py` CSV tests (summary block, columns, chain lines).

## Verification
1. `.venv/Scripts/python -m pytest -q`: all pass.
2. Run `start.bat` and check Hybrid Workspaces. The 6 blocked links appear in "need a human check".
   - Mark one as Broken: the Broken counter becomes 1 and an L01 finding appears with "Marked broken by reviewer".
   - Mark the rest as Works: the "still to check" counter reaches 0.
3. Download the findings CSV, open it in Excel, and confirm the summary block, readable columns, and multi-line redirect path.
