# OpenText QA Tool

Checks OpenText web pages before publishing. **Release 1, slice 1: broken links.** The tool loads a page in a real browser, finds every link (including links inside hidden tabs), and checks each one for broken pages, redirects, and empty links.

Roadmap and architecture: [docs/ARCHITECTURE_PLAN.md](docs/ARCHITECTURE_PLAN.md).

## Use it (QA team)

1. Double-click **`start.bat`**. The first run installs everything, which takes a few minutes and needs internet.
2. The browser opens at http://127.0.0.1:8000.
3. Enter the ticket ID (optional) and the page URL, then click **Run check**.
4. Read the report:
   - **Counters:** total, internal, external, and resource links, plus how many are broken, redirected, or need a manual check.
   - **Findings:** what to fix, most serious first. The *Suggestion* column holds the URL to use instead.
   - **All links found:** every link the tool pulled, so you can confirm nothing was missed.
5. **Export findings (CSV)** or **Export all links (CSV)** to attach to the ticket.

### Links that need a human check
Some sites block automated checks with bot protection (for example community.opentext.com behind Imperva, and blogs.opentext.com behind Cloudflare). The tool can't tell whether those links work, so the report lists them under **"N links need a human check"**:

1. Click **Open link** to open the link in your browser.
2. Mark it **Works ✓** or **Broken ✗**.

The counters, findings, and exports update immediately. **Undo** puts a link back on the list. Until every link is marked, the Broken counter also shows "N still to check", so 0 broken is never mistaken for "all clear".

**Making these checks automatic.** Ask OpenText's web team to allowlist a request header for this tool in Cloudflare and Imperva (for example `X-OT-QA-Tool: <secret>`). Then:
- put the header **name** in `governance/rules.yaml` → `allowlist_header`;
- set the secret **value** in the `QA_TOOL_ALLOWLIST_TOKEN` environment variable. Never put it in the file.

The header is only sent to the hosts in `allowlist_hosts` (OpenText domains), so the secret never reaches other sites.

### Exports
**Export findings (CSV)** starts with a short summary (ticket, page, date, totals, warnings), followed by one row per issue. The columns are: Severity, Action (Fix / Check by hand / Review), Issue, Link text, Link on page, Suggested fix, HTTP status, Redirect path (one hop per line), Checked by (Tool / Reviewer), Section, Rule. **Export all links (CSV)** lists every link with a readable result: Working, Broken, Redirect, Check by hand, or Not checked.

By default only the page content is checked. Tick **Include header & footer links** to check the global navigation too (about 500 more links).

### What the findings mean

| Rule | Finding | Severity |
|---|---|---|
| L01 | Broken link: 404, 410, OpenText's "page not found" (490), a 5xx server error, a timeout, or an unreachable site | Critical |
| L02 | Could not verify: the site blocks automated checks (e.g. community.opentext.com). Open it by hand | Info (review) |
| L03 | Permanent redirect (301/308): update the link to the suggested URL | Minor |
| L04 | Temporary redirect (302/303/307): confirm it is intended | Info |
| L05 | Redirect chain (2 or more hops): link straight to the final URL | Major |
| L09 | Empty or placeholder link (`href=""`, `#`, `javascript:`) | Major |

### Changing the rules

Edit [governance/rules.yaml](governance/rules.yaml). It holds the internal hosts, resource file types, which HTTP statuses count as broken, timeouts, and each rule's severity. Changes apply to the next run, with no restart needed.

## Command line

```
.venv\Scripts\python -m engine.cli https://www.opentext.com/products/hybrid-workspaces --findings-csv findings.csv --links-csv links.csv
```

Add `--include-global` to include header and footer links. The exit code is 1 when any critical finding exists.

## Develop

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[test]
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m pytest -q
```

Layout:

| Folder | What it holds |
|---|---|
| `engine/` | load → extract → check → rules → inventory |
| `app/` | FastAPI dashboard |
| `report/` | exports |
| `governance/` | editable rules |
| `tests/` | local HTTP server fixtures; no internet needed |
