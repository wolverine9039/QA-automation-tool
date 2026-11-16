# Release 1, Slice 1: Broken Link Checker (implementation plan)

**Spec:** `docs/ARCHITECTURE_PLAN.md`, sections Release 1 (rules L01–L05 and L09, HTTP checker, link inventory), Platform Architecture, and Dashboard.
**Out of this slice:** L06–L08 and L10 (legacy, restricted, relative-URL, and tab-behaviour rules), SQLite history, screenshot annotation, Excel/PDF export, scoring. These are the next slices.

## Global Constraints
- Python 3.13 venv at `.venv`. Run tests with `.venv/Scripts/python -m pytest -q`.
- Async Playwright everywhere. HTTP checks use a Playwright `APIRequestContext`, so they share the browser's UA and cookies.
- Facts from probing opentext.com (2026-11-16):
  - A missing page returns **490**, not 404, so 490 counts as broken.
  - `community.opentext.com` sits behind Imperva. Automated requests get a malformed response ("Parse Error"), which must be reported as **unverifiable**, not broken.
  - There is no `<main>` element. About 450 links are in `<header>`, about 50 in `<footer>`, and content links sit outside both.
  - Links inside hidden tabs exist in the DOM already, so no tab expansion is needed to extract them.
- Region = `header` if inside `header,[role=banner]`, `footer` if inside `footer,[role=contentinfo]`, else `main`. The default scope is `main` only.
- All tunables live in `governance/rules.yaml`.

## Interfaces
- `engine.config.load_config(path=None) -> dict`
- `engine.models`: dataclasses `LinkRecord`, `CheckResult`, `Finding`, `RunResult`, each with `to_dict()`.
- `engine.links.classify.classify_link(raw_href: str, abs_url: str, cfg: dict) -> str`. Returns one of `empty|anchor|mailto|tel|other|resource|internal|external`.
- `engine.http.link_checker.check_urls(request_ctx, urls: list[str], cfg: dict) -> dict[str, CheckResult]`
- `engine.extract.links.extract_links(page, cfg) -> list[LinkRecord]`
- `engine.load.page_loader.load_page(page, url, cfg) -> int | None` (returns the page's HTTP status)
- `engine.rules.link.broken_links.evaluate(links, results, cfg) -> list[Finding]`
- `engine.inventory.summarize(links, results) -> dict`
- `engine.runner.run(url, include_global=False, cfg=None) -> RunResult` (async) and `run_sync(...)`, which runs it on a fresh event loop in the calling thread
- `report.export.findings_csv(run) -> str`, `report.export.links_csv(run) -> str`

---

## Task 1: Project scaffold, config, and local test server

Files: `pyproject.toml`, `engine/__init__.py`, `engine/config.py`, `governance/rules.yaml`, `tests/conftest.py`, `tests/test_config.py`.

**`governance/rules.yaml` keys** (under `link_check:`):
- `internal_hosts: [www.opentext.com, opentext.com]`
- `resource_extensions: [pdf, doc, docx, xls, xlsx, ppt, pptx, zip, csv, mp4]`
- `broken_statuses: [404, 410, 490]` (all 5xx are also broken)
- `unverifiable_statuses: [401, 403, 429, 999]`
- `bot_protection_markers: ["Incapsula", "_Incapsula_Resource", "cf-chl", "Attention Required"]`
- `timeout_ms: 15000`, `retries: 1`, `max_redirects: 10`, `concurrency: 8`, `per_host_concurrency: 4`

`load_config()` reads `governance/rules.yaml` relative to the repo root. If an explicit path is given, it reads that file instead.

**`tests/conftest.py`:** a `server` fixture (session scope) running a `ThreadingHTTPServer` on a free port in a daemon thread. It yields the base URL. Routes:

| Route | Response |
|---|---|
| `/ok` | 200 |
| `/missing` | 404 |
| `/gone` | 410 |
| `/ot404` | 490 |
| `/error` | 500 |
| `/r301` | 301 → `/ok` |
| `/r302` | 302 → `/ok` |
| `/r307` | 307 → `/ok` |
| `/chain1` | 301 → `/chain2` (relative Location), then 301 → `/ok` |
| `/loop1` | ↔ `/loop2` |
| `/to404` | 301 → `/missing` |
| `/slow` | sleeps 3 s, then 200 |
| `/head405` | HEAD 405, GET 200 |
| `/forbidden` | 403 |
| `/challenge` | 200 with a small body containing `_Incapsula_Resource` |
| `/fixtures/<name>` | serves `tests/fixtures/<name>` |

Also a `test_cfg` fixture: the loaded config with `timeout_ms: 1000` and `retries: 0`.

**Tests (`tests/test_config.py`):**
- `test_load_config_has_link_check_defaults`: asserts that 490 is in `broken_statuses` and that `www.opentext.com` is in `internal_hosts`.
- `test_server_fixture_serves_routes`: `/missing` returns 404 and `/ok` returns 200 (via urllib).

Steps: write the tests → run → Expected: fail (no `engine.config`). Implement → run → Expected: 2 passed. Commit `chore: scaffold project, config, test server`.

## Task 2: Models and link classification

Files: `engine/models.py`, `engine/links/__init__.py`, `engine/links/classify.py`, `tests/test_classify.py`.

**`LinkRecord`:** `raw_href, abs_url, text, target, rel, region, visible, selector, bbox (dict|None), kind`.

**`CheckResult`:** `url, outcome ("ok"|"broken"|"unverifiable"), status (int|None), final_url, chain (list of [url, status] hops before the final), error (str|None)`.

**`Finding`:** `rule_id, area="Link QA", category, severity, status ("issue"|"review"), message, suggestion, element_text, raw_value, url, selector, region, bbox, http_status, chain`.

**`RunResult`:** `url, final_url, page_status, include_global, started_at, duration_s, links, results, findings, inventory`.

**`classify_link` order:**
1. Empty/whitespace, `#`, or `javascript:` → `empty`
2. Starts with `#` → `anchor`
3. `mailto:` → `mailto`; `tel:` → `tel`
4. Scheme not http/https → `other`
5. Path extension in `resource_extensions` → `resource`
6. Raw href relative, or host in `internal_hosts` → `internal`
7. Anything else → `external`

**Tests:** these cases are parametrized in one test, `test_classify_link`:

| Input | Expected |
|---|---|
| `""` | empty |
| `"#"` | empty |
| `"javascript:void(0)"` | empty |
| `"#section"` | anchor |
| `"mailto:a@b.com"` | mailto |
| `"tel:123"` | tel |
| `"ftp://x"` | other |
| `/en/media/ds.pdf` | resource |
| `https://www.opentext.com/x.PDF` | resource |
| `/products/x` | internal |
| `https://opentext.com/x` | internal |
| `https://www.linkedin.com/x` | external |

Also `test_models_to_dict_roundtrip_keys`.

Steps: test → Expected: fail (import error). Implement → Expected: all pass. Commit `feat: link models and classification`.

## Task 3: HTTP link checker

Files: `engine/http/__init__.py`, `engine/http/link_checker.py`, `tests/test_link_checker.py`.

**Behaviour, per unique URL:**
- Follow redirects manually: `fetch(url, method, max_redirects=0, timeout=cfg.timeout_ms)`. Resolve `Location` with `urljoin`, record each hop `[url, status]`, stop at `max_redirects`. A repeated URL is a loop → broken, `error="Redirect loop"`.
- Send HEAD first. If the HEAD status is ≥ 400, retry that hop with GET.
- On a GET response with status < 300, read the body. If it contains any `bot_protection_markers` → unverifiable.
- A request error whose message contains "Parse Error" → unverifiable. Other request errors (timeout, refused, DNS) are retried `retries` times, then reported as broken with `error` set to the first line of the message.
- Final status in `broken_statuses`, or ≥ 500 → broken. In `unverifiable_statuses` → unverifiable. Otherwise < 400 → ok, and any other ≥ 400 → broken.
- Concurrency: a global semaphore (`concurrency`) plus one semaphore per host (`per_host_concurrency`). Results are cached in the returned dict; duplicate input URLs are checked once.

**Tests** (each uses `server` + `test_cfg` + a real `playwright.request.new_context()`):

| Test | Expected |
|---|---|
| `test_ok` | ok, status 200, chain `[]` |
| `test_404_410_490_500_are_broken` | parametrized; broken with the matching status |
| `test_permanent_redirect_records_chain` | `/r301` → ok, chain `[[.../r301, 301]]`, `final_url` ends `/ok` |
| `test_chain_with_relative_location` | `/chain1` → 2 hops, ok |
| `test_redirect_loop_is_broken` | `error == "Redirect loop"` |
| `test_redirect_to_404_is_broken` | status 404, chain length 1 |
| `test_timeout_is_broken` | `/slow` → broken, error mentions timeout |
| `test_head_405_falls_back_to_get` | ok, 200 |
| `test_403_is_unverifiable` | |
| `test_bot_challenge_body_is_unverifiable` | |
| `test_connection_refused_is_broken` | port of a closed socket |
| `test_duplicate_urls_checked_once` | 2 identical inputs → 1 key |

Steps: test → Expected: fail. Implement → Expected: all pass. Commit `feat: HTTP link checker with redirect chains and bot-protection handling`.

## Task 4: Page loader and link extraction

Files: `engine/load/__init__.py`, `engine/load/page_loader.py`, `engine/extract/__init__.py`, `engine/extract/links.py`, `tests/fixtures/links_page.html`, `tests/test_extract.py`.

**`load_page`:** `goto(url, wait_until="domcontentloaded", timeout=60s)`. Wait for `networkidle` (15 s, a timeout is ignored). Scroll the page in viewport steps to trigger lazy loading, then return to the top. Return the response status (or None).

**`extract_links`:** one `page.evaluate` over every `a[href]`. It captures:
- `raw_href` from `getAttribute('href')`, and `abs_url` from `a.href`
- `text`: whitespace-collapsed `innerText || textContent`, falling back to `aria-label`, then to the alt text of an `img` inside
- `target`, `rel`, `region`
- `visible`: `getClientRects().length > 0`
- `selector`: `#id`, or a tag:nth-of-type path
- `bbox`: document coordinates

`kind` is filled in Python with `classify_link`.

**Fixture page** `links_page.html` contains:
- a `<header>` link to `/ok`
- a `<footer>` link to `/missing`
- main links: `/ok`, `/missing`, `/r301`, `href=""`, `href="#"`, `mailto:`, `/ok#frag`, an image-only link `<a href="/ok"><img alt="Logo"></a>`
- a link inside a `display:none` tab panel pointing to `/gone`

**Tests:**
- `test_extracts_all_links_with_regions`: the counts per region are header 1, footer 1, main 9.
- `test_raw_href_preserved_vs_resolved`: `raw_href == "/ok"` and `abs_url` starts with the server base.
- `test_hidden_tab_link_extracted_and_marked_invisible`
- `test_image_link_text_falls_back_to_alt`: `"Logo"`
- `test_kinds_assigned`: `href=""` is `empty` and `mailto:` is `mailto`.

Steps: test → Expected: fail. Implement → Expected: pass. Commit `feat: page loader and link extraction`.

## Task 5: Broken-link rules and inventory

Files: `engine/rules/__init__.py`, `engine/rules/link/__init__.py`, `engine/rules/link/broken_links.py`, `engine/inventory.py`, `tests/test_broken_link_rules.py`.

**Rules:** one finding per link occurrence. A checked URL is `abs_url` without its fragment, for kinds internal, external, and resource.

| ID | Condition | Severity / status |
|---|---|---|
| L09 | kind `empty` | major, issue. Message: "Empty or placeholder link" |
| L01 | outcome broken | critical, issue. Message has the status or error. Suggestion: fix or remove the link |
| L02 | outcome unverifiable | info, review. Message: "Could not verify automatically (bot protection or access restricted); check manually" |
| L05 | outcome ok and hops > 1 | major, issue. The chain goes in the message |
| L03 | outcome ok, hops == 1, status 301/308 | minor, issue |
| L04 | outcome ok, hops == 1, status 302/303/307 | info, issue |

For L03–L05, the suggestion is the final URL. When the link is internal and `raw_href` was relative, the suggestion is the final URL's path + query instead.

**`summarize`:** returns counts for `total, internal, external, resource, other` (empty, anchor, mailto, tel, other), plus `broken, redirected, unverifiable` (counted per link occurrence).

**Tests:** pure, built from constructed `LinkRecord`/`CheckResult` values:
- `test_empty_link_is_L09`
- `test_broken_is_L01_critical`
- `test_unverifiable_is_L02_review`
- `test_single_301_is_L03_with_relative_suggestion`
- `test_302_is_L04`
- `test_chain_is_L05_only` (no L03 as well)
- `test_ok_link_has_no_findings`
- `test_mailto_not_checked_no_findings`
- `test_summarize_counts`

Steps: test → Expected: fail. Implement → Expected: pass. Commit `feat: broken-link rules L01-L05, L09 and link inventory`.

## Task 6: Runner, CSV export, and CLI

Files: `engine/runner.py`, `engine/cli.py`, `report/__init__.py`, `report/export.py`, `tests/test_runner.py`.

**`run`:**
1. Launch headless Chromium, create a context and page, then `load_page` and `extract_links`.
2. Filter to the `main` region unless `include_global` is set.
3. Check the unique checkable URLs via `context.request`.
4. Run `evaluate` and `summarize`, close the browser, and return the `RunResult`, with findings sorted critical → major → minor → info.

**`run_sync`:** `asyncio.run(run(...))`. The dashboard calls it from a worker thread, so Playwright always gets a Proactor loop on Windows.

**`report/export.py`:** CSV with headers.
- Findings columns: Severity, Status, Rule, Category, Message, Suggestion, Link text, Href, URL, HTTP status, Redirect chain, Region, Selector.
- Links columns: Region, Kind, Text, Href, Resolved URL, Target, Visible, Outcome, HTTP status, Final URL.

**`cli.py`:** `python -m engine.cli URL [--include-global] [--findings-csv F] [--links-csv F]`. Prints the inventory and a findings table.

**Tests** (against `server` + `/fixtures/links_page.html`):
- `test_run_main_scope`: header and footer links are excluded. L01 is found for `/missing` and for the hidden `/gone`, L03 for `/r301`, and L09 twice. The inventory total is 9.
- `test_run_include_global_adds_header_footer`: the total is 11, and the footer `/missing` adds an L01.
- `test_csv_exports_have_headers_and_rows`

Steps: test → Expected: fail. Implement → Expected: pass. Commit `feat: runner, CSV export, CLI`.

## Task 7: Dashboard and launcher

Files: `app/__init__.py`, `app/main.py`, `app/templates/base.html`, `app/templates/index.html`, `app/templates/report.html`, `app/static/style.css`, `start.bat`, `README.md`, `tests/test_app.py`.

**Routes:**

| Route | Behaviour |
|---|---|
| `GET /` | Form: Ticket ID (optional), Page URL, "Include header & footer links" checkbox |
| `POST /run` | Validates that the URL is http(s); otherwise re-renders the form with an error and returns 400. Runs `await asyncio.to_thread(run_sync, ...)`, stores the result in an in-memory dict under a uuid, and returns a 303 redirect to `/runs/{id}` |
| `GET /runs/{id}` | Inventory counters, then the findings table (severity colours, chain shown), then the full link inventory table (answering "see exactly what was pulled"). Unknown id → 404 |
| `GET /runs/{id}/findings.csv`, `GET /runs/{id}/links.csv` | CSV downloads |

Jinja autoescaping stays on, and the server binds to 127.0.0.1.

**`start.bat`:** creates `.venv` if it is missing, runs `pip install -e .` and `playwright install chromium`, then starts `uvicorn app.main:app --host 127.0.0.1 --port 8000` and opens the browser.

**Tests** (FastAPI TestClient; `httpx` is a test dependency):
- `test_index_renders_form`
- `test_run_rejects_non_http_url` (400)
- `test_run_and_report_end_to_end`: POST the fixture URL, follow the redirect; the report contains "Broken link" and the inventory total; `findings.csv` returns 200 with `text/csv`.
- `test_unknown_run_404`

Steps: test → Expected: fail. Implement → Expected: pass. Commit `feat: dashboard and one-click launcher`.

---

## Review Focus
These are not covered by the tests:
- Real-site behaviour at scale (about 50 main links; about 550 with global links included).
- Imperva and other WAF variants.
- Relative `Location` headers on real servers.
- Event-loop interaction between uvicorn and Playwright on Windows.
- XSS through link text or URLs rendered in the report.
- CSV formula injection (link text starting with `=`) when opened in Excel.

## Verification (after Task 7)
1. Run `.venv/Scripts/python -m pytest -q`. Expected: all pass.
2. Run `.venv/Scripts/python -m engine.cli https://www.opentext.com/products/hybrid-workspaces`. Expected: about 50 main links. Community links come out as L02 unverifiable, and no false L01s; spot-check every L01 manually.
