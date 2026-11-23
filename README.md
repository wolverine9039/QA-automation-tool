# OpenText QA Tool

Checks OpenText web pages before publishing. **Release 1: link governance.** The tool loads a page in a real browser, finds every link (including links inside hidden tabs) and every embedded media source, and checks them for broken pages, redirects, empty links, legacy Vidyard video URLs, restricted references, and internal links written as full URLs.

Roadmap and architecture: [docs/ARCHITECTURE_PLAN.md](docs/ARCHITECTURE_PLAN.md).

## Use it (QA team)

1. Double-click **`start.bat`**. The first run installs everything, which takes a few minutes and needs internet.
2. The browser opens at http://127.0.0.1:8000.
3. Enter the page URL, then click **Run check**.
4. Read the report:
   - **Counters:** total, internal, external, and resource links, plus how many are broken, redirected, legacy (old Vidyard URLs and restricted references), or need a manual check.
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
**Export findings (CSV)** starts with a short summary (page, date, scope, totals, issues by severity, warnings), followed by one row per distinct issue; a link repeated on the page (e.g. in several tabs) is one row with a *Times on page* count. The columns are: Severity, Action (Fix / Check by hand / Review), Issue, Link text, Link on page, Times on page, Suggested fix, HTTP status, Redirect path (one hop per line), Checked by (Tool / Reviewer), Section, Rule. **Export all links (CSV)** lists every link with a readable section (Page content / Header / Footer), type, and result: Working, Broken, Redirect, Check by hand, or Not checked. HTTP status is left blank for links blocked by bot protection, and Final URL is filled only when it differs from the link.

By default only the page content is checked. Tick **Include header & footer links** to check the global navigation too (about 500 more links).

### What the findings mean

| Rule | Finding | Severity |
|---|---|---|
| L01 | Broken link: 404, 410, OpenText's "page not found" (490), a 5xx server error, a timeout, or an unreachable site | Critical |
| L02 | Could not verify: the site blocks automated checks (e.g. community.opentext.com). Open it by hand | Info (review) |
| L03 | Permanent redirect (301/308): update the link to the suggested URL | Minor |
| L04 | Temporary redirect (302/303/307): confirm it is intended | Info |
| L05 | Redirect chain (2 or more hops): link straight to the final URL | Major |
| L06 | Legacy Vidyard video URL (link or embedded player): `opentext.hubs.vidyard.com/watch/...` → use the suggested `videos.opentext.com/watch/...`; any other `vidyard.com` URL is flagged to confirm | Major |
| L07 | Restricted reference (link or embed) containing `community.opentext.com`, `microfocus`, or `solutions/aviator`: replace or remove according to current standards | Major (review) |
| L08 | Internal link written as a full URL (`https://www.opentext.com/products/x`): use the suggested relative path (`/products/x`) | Minor |
| L09 | Empty or placeholder link (`href=""`, `#`, `javascript:`) | Major |

### Changing the rules

Edit [governance/rules.yaml](governance/rules.yaml). It holds the internal hosts, resource file types, which HTTP statuses count as broken, timeouts, the legacy Vidyard pattern and its replacement, the restricted terms, and each rule's severity. Changes apply to the next run, with no restart needed.

## Command line

```
.venv\Scripts\python -m engine.cli https://www.opentext.com/products/hybrid-workspaces --findings-csv findings.csv --links-csv links.csv
```

Add `--include-global` to include header and footer links. The exit code is 1 when any critical finding exists.

## Deploy to GCP (public link)

The dashboard runs on Cloud Run as a public service (anyone with the link can use it). One-off setup, then deploy:

```
gcloud projects create <project-id> --organization=<org-id> --name="OpenText QA Tool"
gcloud billing projects link <project-id> --billing-account=<billing-account-id>
powershell -ExecutionPolicy Bypass -File deploy\cloudrun\deploy.ps1 -Project <project-id>
```

Re-run `deploy.ps1` to ship an update (it builds from the working folder, so commit first). It builds the `Dockerfile` with Cloud Build (`.gcloudignore` keeps `input/`, tests and docs out of the upload) and runs it as the `qa-tool` service account, which has no roles.

The deploy sets `QA_TOOL_PUBLIC=1`, which:

- rejects pages on internal addresses (localhost, private networks, the cloud metadata server)
- caps checks at 200 per day (UTC); after that people see "daily limit reached"

Two checks run at a time and others wait. `--max-instances 1` is required because runs and the daily count live in memory; they are also lost when the service idles to zero, so download CSVs you want to keep. Checks from Google's datacenter IPs hit bot protection more often than from a laptop, so expect more links under "need a human check".

Logs: `gcloud run services logs read qa-tool --region us-central1 --project <project-id>`

### Custom domain and static IP

`deploy\cloudrun\setup_domain.ps1 -Project <project-id>` (run once after `deploy.ps1`, safe to re-run) reserves a static IP and puts an HTTPS load balancer in front of the service for `qa-tool.buildwithmayank.tech`, which is proxied by Cloudflare. It prints the two Cloudflare DNS records to add: an `A` record to the IP (Proxied) and an `_acme-challenge` `CNAME` (DNS only) that lets Google issue the certificate. Set Cloudflare SSL/TLS to **Full (strict)**. This domain is for internal use; give the client the Firebase URL below. If Cloud Armor quota is available, the script also limits the load balancer to Cloudflare's IPs; on projects with a quota of 0 it skips that step with a warning.

### Client URL (Firebase Hosting)

The client gets **https://opentext-qa-tool.web.app**, a neutral address with no personal domain. `deploy\firebase\setup_hosting.ps1 -Project <project-id>` (safe to re-run) adds Firebase to the project, creates the Hosting site and sends every path to the Cloud Run service; it also sets Cloud Run ingress to `all`, which Firebase needs. The first time, someone who owns the project must click "Add Firebase" once in the Firebase console to accept Firebase's terms.

Firebase stops waiting for Cloud Run after **60 seconds** per request. A typical check takes about 20 seconds; a page with many slow links could hit the limit and show a 504.

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
