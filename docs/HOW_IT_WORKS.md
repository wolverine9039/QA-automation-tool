# OpenText QA Tool: How It Works

A technical guide to how the tool is built and how it runs. It covers the full workflow, what each file is for, what each function does, how to configure the tool, and its known limits.

- **Scope:** Release 1 (Phase 1), link governance: rules L01–L09.
- **Branch:** `r1-broken-links`.
- **Tests:** 108 pass (`pytest -q`).
- **Roadmap and later releases:** [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md).
- **Day-to-day usage for the QA team:** [README.md](../README.md).

---

## 1. What the tool does

You give the tool one OpenText page URL. It then:

1. Opens the page in a real Chromium browser, so content rendered by JavaScript or loaded lazily is present.
2. Collects every `<a href>` on the page, including links inside closed tabs and accordions, plus every embedded media source (`iframe`, `video`/`source`, `audio`, `embed`, `object`). Scripts are skipped: `<head>` and template scripts, such as Vidyard's player, are not page content.
3. Sorts each link into one kind: internal, external, resource, anchor, mailto, tel, empty, or other.
4. Checks every unique internal, external and resource URL over HTTP, and records each redirect hop.
5. Turns the results into **findings**: broken links, redirects, redirect chains, legacy Vidyard URLs, restricted references, absolute internal URLs, empty links, and links it could not verify.
6. Shows a report in a local web dashboard. A person can mark bot-protected links by hand there.
7. Exports findings and the full link inventory as CSV files to attach to the ticket.

It can also run from the command line, which is useful in CI because the exit code is 1 when any critical finding exists.

### Technology

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Browser automation and HTTP checks | Playwright (Chromium) |
| Web dashboard | FastAPI, Jinja2 templates, uvicorn |
| Rules config | YAML (`governance/rules.yaml`) |
| Tests | pytest, pytest-asyncio, httpx; local HTTP fixtures, no internet needed |

---

## 2. Architecture at a glance

```
            +------------------+        +-------------------+
 QA user -> | app/ (FastAPI)   |        | engine/cli.py     | <- command line / CI
            | form, report,    |        +---------+---------+
            | review, CSV      |                  |
            +--------+---------+                  |
                     |  run_sync(url, include_global)
                     v                            v
            +---------------------------------------------+
            | engine/runner.py  (orchestrates one run)    |
            |                                             |
            |  load_page -> extract links+embeds -> scope |
            |     -> check_urls -> evaluate -> summarize  |
            +----+---------+----------+---------+---------+
                 |         |          |         |
     engine/load/  engine/extract/  engine/http/  engine/rules/link/
     page_loader   links + links/   link_checker  broken_links
                   classify                       + engine/inventory
                                 |
                     governance/rules.yaml  (read by engine/config.py)
                                 |
                     report/export.py  (CSV output)
```

Every layer passes the dataclasses in `engine/models.py` (`LinkRecord`, `CheckResult`, `Finding`, `RunResult`). Each layer depends only on the layers below it. The engine knows nothing about the web app.

---

## 3. End-to-end workflow

### 3.1 Starting the tool

`start.bat` is the one-click launcher.

1. It switches to the folder the script is in.
2. If something already listens on port 8000 (usually the tool in another window), it says so and stops, rather than opening the old copy.
3. On the first run only (when there is no `.venv\Scripts\python.exe`), it creates `.venv` and upgrades pip.
4. When `pyproject.toml` differs from `.venv\installed-pyproject.toml` (first run, or an update changed the packages), it:
   - installs the package in editable mode (`pip install -e .`);
   - downloads Chromium (`playwright install chromium`);
   - copies `pyproject.toml` to `.venv\installed-pyproject.toml`, so the next start skips this step.
5. It opens `http://127.0.0.1:8000` in the default browser.
6. It starts `uvicorn app.main:app` on `127.0.0.1:8000`. Closing the window stops the tool.

If Python is missing or the install fails, it prints a plain-English message and pauses.

### 3.2 Running a check

```
Browser                     app/main.py                 engine/runner.py
  |  GET /                       |                             |
  |----------------------------->| index(): render form        |
  |  POST /run (url,             |                             |
  |   include_global)            |                             |
  |----------------------------->| start_run():                |
  |                              |  validate http(s) URL       |
  |                              |  asyncio.to_thread(run_sync)|
  |                              |---------------------------->| run():
  |                              |                             |  1. launch Chromium
  |                              |                             |  2. load_page()
  |                              |                             |  3. extract_links(), extract_embeds()
  |                              |                             |  4. keep "main" links only
  |                              |                             |     (unless include_global)
  |                              |                             |  5. check_urls() on CHECKABLE kinds
  |                              |                             |  6. close browser
  |                              |                             |  7. page_warnings()
  |                              |                             |  8. _refresh(): evaluate + summarize
  |                              |<----------------------------| RunResult
  |                              |  store in RUNS[run_id]      |
  |  303 -> /runs/{run_id}       |                             |
  |<-----------------------------|                             |
  |  GET /runs/{run_id}          |                             |
  |----------------------------->| report(): render report     |
```

The run happens in a worker thread on a fresh event loop. On Windows, Playwright must start a browser subprocess, and that needs an event loop that can create subprocesses. uvicorn's loop may not be one.

### 3.3 Inside one run, step by step

| Step | Function | What happens |
|---|---|---|
| 1 | `async_playwright()` and `chromium.launch()` | Starts a headless browser with one context and one page. |
| 2 | `load_page` | Navigates with a 60 s timeout and waits up to 15 s for network idle (pages with analytics beacons never go idle, so a timeout is ignored). It then scrolls down one screen at a time, at most 60 times, so lazy sections render, and returns to the top. It returns the page's HTTP status. |
| 3 | `extract_links`, `extract_embeds` | Runs JavaScript in the page to read every `a[href]` (classified in Python), and every embed source (`src`, lazy `data-src`, or `object[data]`; kind `embed`). Embeds are not checked over HTTP; they feed rules L06 and L07. |
| 4 | scope filter | Unless **include header & footer** is ticked, only links and embeds in the `main` region are kept. Header and footer navigation adds about 500 links. |
| 5 | `check_key` | Removes the `#fragment` from each URL. Fragments never reach the server, so `/a#x` and `/a#y` are one check. |
| 6 | `check_urls` | Checks each unique URL once, with limited concurrency. It uses `context.request`, which shares the page's cookies, so web application firewalls are less likely to block every check. |
| 7 | `page_warnings` | Adds warnings that the report may not reflect the real page (see 3.4). |
| 8 | `_refresh` | Runs `broken_links.evaluate` (L01–L05, L09) and `governance.evaluate` (L06–L08), and sorts the findings critical, then major, minor, info. Then `summarize` builds the counters and `legacy_count` adds `legacy`. |

### 3.4 Page-level warnings

These appear at the top of the report and in both CSVs.

- The page itself returned HTTP 400 or above.
- The page HTML contains a bot-protection marker, so it is a challenge page and not the real page.
- The page redirected to a different URL.
- No links were found, which suggests the page did not load properly.

### 3.5 Human review of bot-protected links

Some OpenText sites block automated checks. community.opentext.com is behind Imperva and blogs.opentext.com is behind Cloudflare. The checker cannot tell whether those links work, so it marks them `unverifiable` and raises rule L02.

1. The report lists each unverifiable URL once, under **"N links need a human check"**.
2. The reviewer clicks **Open link**, then **Works ✓** or **Broken ✗**. The button sends `POST /runs/{id}/review` with the URL and a verdict.
3. `apply_review` changes the stored `CheckResult`:
   - **ok:** outcome becomes `ok` and `checked_by` becomes `reviewer`.
   - **broken:** outcome becomes `broken`, `checked_by` becomes `reviewer`, and the error reads "Marked broken by reviewer". The link now raises L01.
   - **reset (Undo):** outcome goes back to `unverifiable` and `checked_by` back to `tool`.
   - In every case the status is cleared, because the blocked response's status says nothing about the real page.
4. Findings and counters are recalculated, and the browser returns to the review section. Exports reflect the change straight away.

While any link is still unchecked, the **Broken** counter shows "N still to check", so "0 broken" is never mistaken for "all clear".

### 3.6 Exports

- `GET /runs/{id}/findings.csv` downloads `QA_Findings_<run id>.csv`.
- `GET /runs/{id}/links.csv` downloads `QA_Links_<run id>.csv`.

Both files begin with a summary block (page, check time, scope, totals, warnings; the findings file adds issues by severity), then a blank row, then the table. In the findings file, identical rows (the same issue on the same link, repeated on the page) are merged into one row with a *Times on page* count. Sections and link types use readable labels (Page content, Resource (file), Anchor (same page)...). HTTP status is blank for links blocked by bot protection, because that status comes from the challenge page. They are written as UTF-8 with a BOM so Excel shows non-English characters correctly.

---

## 4. Link classification

`classify_link(raw_href, abs_url, cfg)` checks these conditions in order. The first match wins.

| Order | Condition | Kind | Checked over HTTP? |
|---|---|---|---|
| 1 | `href` is empty, exactly `#`, or starts with `javascript:` | `empty` | No (rule L09) |
| 2 | `href` starts with `#` | `anchor` | No |
| 3 | starts with `mailto:` | `mailto` | No |
| 4 | starts with `tel:` | `tel` | No |
| 5 | resolved URL is not http or https | `other` | No |
| 6 | path ends with an extension in `resource_extensions` | `resource` | Yes |
| 7 | authored `href` is relative, or the host is in `internal_hosts` | `internal` | Yes |
| 8 | anything else | `external` | Yes |

`CHECKABLE = {"internal", "external", "resource"}`.

A protocol-relative `href` such as `//host/x` does **not** count as relative.

## 5. Region detection

The in-page script labels each link `header`, `footer`, or `main`.

- **header:** the link is inside `[role=banner]`, or inside a `<header>` that is not itself inside `main`, `article`, `aside`, `nav` or `section`.
- **footer:** the same test with `[role=contentinfo]` and `<footer>`.
- **main:** everything else.

This follows the HTML rule that a `<header>` inside a card or article is page content, not the site banner.

## 6. HTTP checking

For each unique URL, `_check` follows redirects by hand: `max_redirects` is set to 0 on each request, and the tool follows the `Location` header itself. This is how the full chain is recorded.

```
current = url
repeat up to max_redirects + 1 times:
    status, location, body, challenged = _fetch(current)
        on a Playwright error:   "Parse Error" -> unverifiable (Imperva), anything else -> broken
    challenge header or bot marker in the body?   -> unverifiable
    status is 301/302/303/307/308 with a Location:
        add [current, status] to the chain
        current = next URL; continue              (no "already seen" check: some sites redirect
                                                   to the same URL once to set a cookie)
    otherwise -> outcome from _outcome(status)
the loop ran out                                  -> broken ("More than N redirects")
```

`_fetch` tries **HEAD** first. If HEAD returns 400 or above, or errors with anything except a timeout, it sends a **GET** with `Range: bytes=0-65535`. Many servers mishandle HEAD, and the range keeps a large PDF or video from downloading in full and timing out as "broken". The first 64 KB of the body is searched for bot-protection markers at any status, because web application firewall block pages also arrive as 403 or 503.

`_outcome(status)` maps a status to an outcome:

| Status | Outcome |
|---|---|
| In `broken_statuses` (404, 410, 490), or 500 and above | `broken` |
| In `unverifiable_statuses` (401, 403, 429, 999) | `unverifiable` |
| Below 400 | `ok` |
| Any other 4xx | `broken` |

490 is the status www.opentext.com returns for "page not found".

**Concurrency.** Up to 8 checks run at once in total (`concurrency`) and up to 4 per host (`per_host_concurrency`). A check takes its host slot *before* a global slot, so a busy host never holds global slots while it waits.

**Retries.** A failed request is retried `retries` times (default 1). A "Parse Error" is not retried, because it is a deliberate block.

**Allowlist header.** `allowlist_header` holds the header *name*, and the `QA_TOOL_ALLOWLIST_TOKEN` environment variable holds the secret *value*. When both are set, the header is added only to requests for hosts in `allowlist_hosts` or their subdomains, so the secret never reaches other sites. This is waiting for OpenText's web team to allowlist the header in Cloudflare and Imperva.

## 7. Rules and findings

`evaluate` creates at most one finding per link on the page. A URL that appears three times on the page gives three findings, each with its own text and location.

| Rule | When | Default severity | Status | Suggestion |
|---|---|---|---|---|
| L01 | Outcome `broken` (bad status, timeout, unreachable, redirect loop, too many redirects, or marked broken by a reviewer) | critical | issue | "Fix the URL or remove the link." |
| L02 | Outcome `unverifiable` | info | review | "Open the link in a browser…" |
| L03 | One redirect hop, 301 or 308 | minor | issue | The final URL, ready to paste |
| L04 | One redirect hop, 302, 303 or 307 | info | issue | The final URL |
| L05 | Two or more redirect hops | major | issue | The final URL |
| L06 | Link or embed matches `legacy_video.pattern` (`opentext.hubs.vidyard.com/watch/{id}`), or its host is or ends with an `other_hosts` entry (`vidyard.com`) | major | issue | `https://videos.opentext.com/watch/{id}`; for other Vidyard URLs, a prompt to use the matching videos.opentext.com link |
| L07 | Link or embed contains a `restricted_references` term (case-insensitive) | major | review | "Replace or remove according to current standards." |
| L08 | Internal or resource link authored as `http(s)://` plus a host in `internal_hosts` | minor | issue | The relative path, with query and `#fragment` kept |
| L09 | Kind `empty` | major | issue | "Add the destination URL, or remove the link." |

Special cases:

- **L09 exception.** A link with `role="button"` and a non-empty `#` or `javascript:` href is a JavaScript control, such as a modal close button. It is skipped. An empty `href=""` is still flagged.
- **Suggested URL** (`_suggested_target`). If the redirect ends on an internal host, or the authored link was relative and stays on the same host, the suggestion is relative (path plus query). This matches the authoring standard and L08. When the checked page is not on an `internal_hosts` host (for example `blogs.opentext.com`), the rules treat only the page's own host as internal, so no relative path points to the wrong site. The original `#fragment` is kept unless the final URL already has one.
- **One link, several findings.** A link can raise more than one rule. For example, a community.opentext.com link raises L07 (restricted) and L02 (could not verify).
- **Legacy counter.** Counts links and embeds matched by L06 or L07.
- **Severity and status** come from `rules.yaml`, so they can be changed without touching code.

---

## 8. File reference

### Root

| File | Purpose |
|---|---|
| `start.bat` | One-click installer and launcher for Windows (see 3.1). |
| `pyproject.toml` | Package metadata, runtime and test dependencies, and pytest settings (`asyncio_mode = auto`, session-scoped event loop). |
| `README.md` | Usage guide for the QA team. |

### `governance/`

| File | Purpose |
|---|---|
| `rules.yaml` | Every setting a non-developer may need to change (see section 9). It is re-read on each run, so no restart is needed. |

### `engine/`: the checking engine

| File | Purpose |
|---|---|
| `models.py` | Dataclasses shared by all layers. |
| `config.py` | Loads `rules.yaml`. |
| `runner.py` | Orchestrates one run, reviewer verdicts, and page warnings. |
| `load/page_loader.py` | Opens and scrolls the page. |
| `extract/links.py` | Pulls links and embed sources out of the rendered page. |
| `links/classify.py` | Link kinds and the URL key used for checking. |
| `http/link_checker.py` | HTTP checking, redirects, bot detection, allowlist header. |
| `rules/link/broken_links.py` | Rules L01–L05 and L09 (from HTTP results). |
| `rules/link/governance.py` | Rules L06–L08 and the Legacy count (from the URLs alone, no HTTP). |
| `inventory.py` | Counter totals. |
| `cli.py` | Command-line entry point. |

### `report/`

| File | Purpose |
|---|---|
| `export.py` | CSV generation, the time formatter, and the totals line. The dashboard and the CLI both use it. |

### `app/`: the dashboard

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, routes, and the in-memory run store. |
| `templates/base.html` | Page layout. |
| `templates/index.html` | The "Check a page" form. Disables the button while a run is in progress. |
| `templates/report.html` | Report: header and actions, warnings, counters, the human-check table, findings, and all links. |
| `static/style.css` | Styling. |

### `tests/`

| File | Covers |
|---|---|
| `conftest.py` | Local HTTP server and shared fixtures. |
| `fixtures/*.html` | Test pages: `links_page`, `embeds_page`, `review_page`, `infinite_scroll`, `xss_page`. |
| `test_classify.py` | Link kinds. |
| `test_extract.py` | Extraction, regions, hidden links, infinite-scroll cap. |
| `test_link_checker.py` | Statuses, redirects, loops, HEAD→GET fallback, bot detection, allowlist header. |
| `test_broken_link_rules.py` | Rule mapping, suggestions, the role=button exception. |
| `test_governance_rules.py` | L06–L08, the Legacy count, relative redirect suggestions. |
| `test_runner.py` | The full pipeline and page warnings. |
| `test_review_and_export.py` | Reviewer verdicts and CSV content and safety. |
| `test_app.py` | Dashboard routes, validation, escaping. |
| `test_config.py` | Loading the config. |

---

## 9. Function reference

### `engine/models.py`

| Name | Description |
|---|---|
| `LinkRecord` | One link found on the page. Fields: `raw_href` (exactly as written), `abs_url` (resolved), `text`, `target`, `region`, `visible`, `selector`, `bbox`, `kind`, `role`. |
| `CheckResult` | The outcome for one URL. Fields: `url`, `outcome` (`ok`, `broken` or `unverifiable`), `status`, `final_url`, `chain` (`[[url, status], ...]`), `error`, `checked_by` (`tool` or `reviewer`). |
| `Finding` | One issue to report. Fields: rule, category, severity, status, message, suggestion, link text, raw value, URL, selector, region, bbox, chain, area. |
| `RunResult` | The whole run: input and final URL, page status, scope, start time, duration, links, results, findings, inventory, warnings, embeds. |

### `engine/config.py`

| Function | Description |
|---|---|
| `load_config(path=None)` | Reads `governance/rules.yaml`, or the given path, with `yaml.safe_load`. Raises `ValueError` with a plain message for broken YAML, an invalid `legacy_video.pattern`, a missing setting, or a rule L01–L09 without `severity` and `status`. The dashboard shows that message. |

### `engine/runner.py`

| Function | Description |
|---|---|
| `run(url, include_global=False, cfg=None)` | Async. Runs the whole pipeline in 3.3 and returns a `RunResult`. Always closes the browser. |
| `run_sync(url, include_global=False, cfg=None)` | Runs `run` on a new event loop with `asyncio.run`. The dashboard and CLI both call it. |
| `_refresh(result, cfg)` | Recalculates `findings` (sorted by `SEVERITY_ORDER`) and `inventory`. |
| `apply_review(result, url, verdict, cfg)` | Applies a reviewer's verdict (`ok`, `broken` or `reset`) and then refreshes. Raises `ValueError` for an unknown verdict or a link that was never unverifiable. With `url=None` it only refreshes. |
| `page_warnings(url, final_url, page_status, page_html, links, cfg)` | Returns the list of page-level warnings (3.4). |

### `engine/load/page_loader.py`

| Function | Description |
|---|---|
| `load_page(page, url, cfg)` | Navigates, waits, scrolls to load lazy content, and returns the HTTP status or `None`. Uses `NAV_TIMEOUT_MS=60000`, `IDLE_TIMEOUT_MS=15000` and `MAX_SCROLL_STEPS=60`. |

### `engine/extract/links.py`

| Name | Description |
|---|---|
| `_EXTRACT_JS` | Script that runs in the page. It builds a CSS selector for each link, works out the region, and reads the text. Text falls back in this order: `innerText`, `textContent`, `aria-label`, then the `alt` of an image inside the link. It also records visibility (`getClientRects`) and the page-relative position. |
| `_HELPERS_JS` | Shared in-page helpers: `cssPath`, `region`, `clean`, and `where` (region, visibility, selector, bbox). |
| `_EMBEDS_JS` | Reads `iframe, video, source, audio, embed[src], object[data]` (no `script`). The value is `src`, else `data-src` (lazy-loaded), or `data` for `object`; elements without one are skipped. Text is the tag name plus `title`. |
| `extract_links(page, cfg)` | Runs the script and returns `LinkRecord` objects with `kind` filled in. |
| `extract_embeds(page)` | Runs `_EMBEDS_JS` and returns `LinkRecord` objects with `kind="embed"`. |

### `engine/links/classify.py`

| Function | Description |
|---|---|
| `classify_link(raw_href, abs_url, cfg)` | Returns the link kind (section 4). |
| `check_key(abs_url)` | The URL without its fragment. This is the key in `results`. |

### `engine/http/link_checker.py`

| Function | Description |
|---|---|
| `check_urls(request_ctx, urls, cfg)` | Removes duplicates, then checks all URLs concurrently with global and per-host limits. Returns `{url: CheckResult}`. |
| `_check(ctx, url, lc)` | Follows redirects by hand, detects loops and the redirect limit, and decides the outcome. |
| `_outcome(status, lc)` | Maps a status to `ok`, `broken` or `unverifiable`. |
| `_fetch(ctx, url, lc)` | HEAD, then a ranged GET if needed. Returns `(status, location, body_start, challenged)`. |
| `_challenged(resp)` | True when Cloudflare sends `cf-mitigated: challenge`. |
| `_allowlist_header(url, lc)` | The secret header, only for allowlisted hosts. |
| `_request(ctx, url, method, lc, headers)` | A single `fetch` with retries and redirects turned off. |
| `_first_line(e)` | Short, readable form of a Playwright error. |

### `engine/rules/link/broken_links.py`

| Function | Description |
|---|---|
| `evaluate(links, results, cfg)` | Loops over links and returns the list of findings. |
| `_from_result(link, res, cfg)` | Maps one `CheckResult` to L01, L02, L03, L04, L05, or no finding. |
| `_suggested_target(link, res)` | Builds the replacement URL (relative when possible, fragment kept). |
| `_finding(rule_id, link, cfg, category, message, suggestion, res)` | Builds a `Finding`, with severity and status taken from the config. |

### `engine/inventory.py`

| Function | Description |
|---|---|
| `summarize(links, results)` | Counts per link (not per unique URL): `total`, `internal`, `external`, `resource`, `other`, `broken`, `redirected` (ends `ok` after a redirect; a redirect to a broken page counts as broken only), `unverifiable`. The runner adds `legacy` from `governance.legacy_count`. |

### `engine/rules/link/governance.py`

| Function | Description |
|---|---|
| `evaluate(links, embeds, cfg)` | Returns L06, L07 and L08 findings. Empty links are skipped; L08 applies to links only. |
| `_legacy_video(raw, lc)` | Returns `(matched, replacement)`. A pattern match expands `replacement`; an `other_hosts` match returns no replacement. |
| `_restricted(raw, lc)` | The first restricted term the value contains, or `None`. |
| `_absolute_internal(link, lc)` | The relative form of an internal link authored as a full URL, or `None`. |
| `is_legacy(item, cfg)` / `legacy_count(items, cfg)` | Whether one item matches L06 or L07, and how many items do. |

### `engine/cli.py`

| Function | Description |
|---|---|
| `main(argv=None)` | Arguments: `url`, `--include-global`, `--findings-csv`, `--links-csv`. Prints the page, warnings, inventory and findings, and writes the CSVs (UTF-8 with BOM). Returns 1 if any finding is critical, otherwise 0. |

### `report/export.py`

| Function | Description |
|---|---|
| `_safe(value)` | Adds a leading `'` to any cell starting with `=`, `+`, `-`, `@`, tab or CR, to stop CSV formula injection. |
| `local_time(iso)` | Converts the stored UTC time to local `YYYY-MM-DD HH:MM`. Also used as a Jinja filter. |
| `totals_line(inv)` | One-line summary, e.g. "120 links · 2 broken · 5 redirected · 4 legacy · 3 to check by hand". |
| `_csv(run, header, rows)` | Writes the summary block, a blank row, the header, and then the rows. |
| `_result_for(run, url, kind)` | Finds the `CheckResult` for a link, or `None` if the link is not checkable. |
| `_action(f)` | Finding to action: L02 gives "Check by hand", other review items or severity info give "Review", anything else gives "Fix". |
| `shown_status(res)` | HTTP status for display; blank when the result is unverifiable. Also the `http_status` filter in the report page. |
| `issues_line(findings)` | Severity breakdown for the summary, e.g. "5 major · 10 minor · 6 info". |
| `findings_csv(run)` | Findings export. One row per distinct issue. Columns: Severity, Action, Issue, Link text, Link on page, Times on page, Suggested fix, HTTP status, Redirect path (one hop per line), Checked by, Section, Rule. |
| `_link_result(res)` | Result to label: Working, Broken, Redirect, Check by hand, or Not checked. |
| `links_csv(run)` | All-links export. Columns: Section, Type, Link text, Link on page, Opens in, Visible, Result, HTTP status, Final URL, Checked by. |

### `app/main.py`

| Route / function | Description |
|---|---|
| `GET /`: `index` | Shows the form. |
| `POST /run`: `start_run` | Validates the URL (it must be http or https with a host; otherwise 400 with the form refilled). Runs the check in a thread and returns 502 if the browser cannot open the page, or 500 with the message if `rules.yaml` has a mistake. Stores the result under a 12-character ID and keeps at most `MAX_RUNS=50`, dropping the oldest. Redirects to the report. |
| `_get(run_id)` | Looks up a run. Returns 404 if it is unknown or was cleared by a restart. |
| `GET /runs/{id}`: `report` | Pairs each link with its result and builds the review rows: one per unverifiable or reviewer-marked URL, using the first link text seen. |
| `POST /runs/{id}/review`: `review` | Calls `apply_review`. Returns 400 for invalid input, otherwise redirects to `#review`. |
| `_csv_response(text, name)` | CSV download response with a cleaned filename and a BOM. |
| `GET /runs/{id}/findings.csv`: `findings_download` | Findings export. |
| `GET /runs/{id}/links.csv`: `links_download` | All-links export. |

---

## 10. Configuration (`governance/rules.yaml`)

| Key | Default | Effect |
|---|---|---|
| `link_check.internal_hosts` | `www.opentext.com`, `opentext.com` | Hosts counted as internal. Relative links are always internal. |
| `link_check.resource_extensions` | pdf, doc(x), xls(x), ppt(x), zip, csv, mp4 | Extensions that make a link a resource. |
| `link_check.broken_statuses` | 404, 410, 490 | Statuses that count as broken. All 5xx are broken anyway. |
| `link_check.unverifiable_statuses` | 401, 403, 429, 999 | Statuses that mean "blocked, check by hand". |
| `link_check.bot_protection_markers` | `Incapsula`, `_Incapsula_Resource`, `cf-chl`, `Attention Required` | Body text that marks a challenge page. Also used for the page-level warning. |
| `link_check.timeout_ms` | 15000 | Timeout per request. |
| `link_check.retries` | 1 | Extra attempts after an error. |
| `link_check.max_redirects` | 10 | Maximum hops before the link counts as broken. |
| `link_check.concurrency` | 8 | Checks running at once in total. |
| `link_check.per_host_concurrency` | 4 | Checks running at once per host. |
| `link_check.allowlist_header` | `""` | Name of the header the web application firewall lets through. The value comes from `QA_TOOL_ALLOWLIST_TOKEN`. |
| `link_check.allowlist_hosts` | `opentext.com` | Hosts (and their subdomains) that receive the header. |
| `link_check.legacy_video.pattern` / `.replacement` | `opentext\.hubs\.vidyard\.com/watch/(id)` → `https://videos.opentext.com/watch/\1` | The L06 match and its suggestion (regex, case-insensitive). |
| `link_check.legacy_video.other_hosts` | `vidyard.com` | Any other URL on these hosts (or their subdomains) is flagged L06 without a direct replacement. |
| `link_check.restricted_references` | `community.opentext.com`, `microfocus`, `solutions/aviator` | The L07 terms (case-insensitive "contains"). |
| `rules.<ID>.severity` / `.status` | see section 7 | Severity and status for each rule. |

Navigation timeouts and the scroll cap are constants in `page_loader.py`, not in the YAML.

---

## 11. Running and developing

```bat
:: Dashboard
start.bat

:: Command line
.venv\Scripts\python -m engine.cli https://www.opentext.com/products/hybrid-workspaces ^
    --findings-csv findings.csv --links-csv links.csv [--include-global]

:: Development setup and tests
python -m venv .venv
.venv\Scripts\python -m pip install -e .[test]
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m pytest -q
```

The tests run against a local HTTP server started in `conftest.py`, so they need no internet access.

### Extending the tool

- **New link rule.** Add the logic to `engine/rules/link/broken_links.py`, or to a sibling module that `runner._refresh` calls. Add its severity and status under `rules:` in the YAML, plus a test.
- **New check area** (later releases). Add a new rules package under `engine/rules/`. It reads the same `LinkRecord` and page data and returns `Finding` objects with its own `area`. The report, CSVs and counters already work with any list of findings.

---

## 12. Known limitations and open items

| Item | Impact | Planned fix |
|---|---|---|
| Runs are stored in memory (`RUNS`, maximum 50) | Reports disappear when the tool restarts | Move to `data/runs.sqlite` in the history slice (marked `shortcut:` in the code) |
| Bot-protected sites (Imperva, Cloudflare) | Those links need a human check | OpenText's web team allowlists the tool's header (already supported) |
| One page per run | No site crawl yet | Later releases (see the architecture plan) |
| A running server keeps old code | Code changes need a restart | Close the window and run `start.bat` again |
