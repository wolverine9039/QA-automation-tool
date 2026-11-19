"""Human review of links the tool could not check, the allowlist header, and readable CSV exports."""
import copy
import csv
import io
import re

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from playwright.async_api import async_playwright

from app.main import app
from engine.config import load_config
from engine.http import link_checker
from engine.http.link_checker import check_urls
from engine.models import CheckResult, LinkRecord, RunResult
from engine.runner import apply_review
from report.export import findings_csv, links_csv

CFG = load_config()
SITE = "https://www.opentext.com"
BLOCKED = "https://community.opentext.com/x"
REDIRECTED = SITE + "/old"


def make_run() -> RunResult:
    links = [
        LinkRecord(raw_href=BLOCKED, abs_url=BLOCKED, text="Community post", target="_blank",
                   region="main", visible=True, selector="a", bbox=None, kind="external"),
        LinkRecord(raw_href="/old", abs_url=REDIRECTED, text="Old page", target="",
                   region="main", visible=True, selector="a", bbox=None, kind="internal"),
    ]
    results = {
        BLOCKED: CheckResult(url=BLOCKED, outcome="unverifiable", status=403, final_url=BLOCKED),
        REDIRECTED: CheckResult(url=REDIRECTED, outcome="ok", status=200, final_url=SITE + "/new",
                                chain=[[REDIRECTED, 301], [SITE + "/mid", 301]]),
    }
    run = RunResult(url=SITE + "/p", final_url=SITE + "/p", page_status=200, include_global=False,
                    started_at="2026-11-17T08:00:00+00:00", duration_s=1.0, links=links, results=results,
                    findings=[], inventory={})
    apply_review(run, None, None, CFG)   # no verdict: just compute findings + inventory
    return run


# --- apply_review --------------------------------------------------------------------------------

def test_unreviewed_blocked_link_is_still_to_check():
    run = make_run()
    assert run.inventory["unverifiable"] == 1
    assert [f.rule_id for f in run.findings] == ["L05", "L07", "L02"]   # community link is also a restricted reference (L07)


def test_review_broken_counts_as_broken_link():
    run = make_run()
    apply_review(run, BLOCKED, "broken", CFG)
    assert run.inventory["broken"] == 1 and run.inventory["unverifiable"] == 0
    l01 = [f for f in run.findings if f.rule_id == "L01"]
    assert len(l01) == 1 and "Marked broken by reviewer" in l01[0].message
    assert run.findings[0].rule_id == "L01"            # still sorted most serious first
    assert run.results[BLOCKED].checked_by == "reviewer"
    assert run.results[BLOCKED].status is None   # the blocked response's status says nothing about the real page


def test_review_ok_clears_the_finding():
    run = make_run()
    apply_review(run, BLOCKED, "ok", CFG)
    assert run.inventory["unverifiable"] == 0 and run.inventory["broken"] == 0
    assert [f.rule_id for f in run.findings] == ["L05", "L07"]   # L07 stays: restricted regardless of the verdict


def test_review_reset_returns_to_check_by_hand():
    run = make_run()
    apply_review(run, BLOCKED, "broken", CFG)
    apply_review(run, BLOCKED, "reset", CFG)
    assert run.inventory["unverifiable"] == 1
    assert run.results[BLOCKED].checked_by == "tool"


@pytest.mark.parametrize("url,verdict", [(BLOCKED, "maybe"), (REDIRECTED, "broken"), (SITE + "/nope", "ok")])
def test_review_rejects_bad_input(url, verdict):
    # bad verdict / a link the tool already checked itself / a URL not in this run
    with pytest.raises(ValueError):
        apply_review(make_run(), url, verdict, CFG)


# --- allowlist header ----------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def request_ctx():
    async with async_playwright() as p:
        ctx = await p.request.new_context()
        yield ctx
        await ctx.dispose()


def allowlist_cfg(test_cfg, hosts):
    cfg = copy.deepcopy(test_cfg)
    cfg["link_check"].update(allowlist_header="X-QA-Test", allowlist_hosts=hosts)
    return cfg


async def test_allowlist_header_sent_to_allowlisted_host(server, request_ctx, test_cfg, monkeypatch):
    # the test server is plain http, so stub the https-only rule (tested below) to prove the header is sent
    monkeypatch.setattr(link_checker, "_allowlist_header", lambda url, lc: {"X-QA-Test": "secret"})
    url = server + "/needs-header"
    res = (await check_urls(request_ctx, [url], allowlist_cfg(test_cfg, ["127.0.0.1"])))[url]
    assert res.outcome == "ok"


def test_allowlist_header_only_over_https(test_cfg, monkeypatch):
    monkeypatch.setenv("QA_TOOL_ALLOWLIST_TOKEN", "secret")
    lc = allowlist_cfg(test_cfg, ["opentext.com"])["link_check"]
    assert link_checker._allowlist_header("https://blogs.opentext.com/x", lc) == {"X-QA-Test": "secret"}
    assert link_checker._allowlist_header("http://www.opentext.com/x", lc) == {}


async def test_allowlist_header_never_sent_to_other_hosts(server, request_ctx, test_cfg, monkeypatch):
    monkeypatch.setenv("QA_TOOL_ALLOWLIST_TOKEN", "secret")
    url = server + "/needs-header"
    res = (await check_urls(request_ctx, [url], allowlist_cfg(test_cfg, ["opentext.com"])))[url]
    assert res.outcome == "unverifiable"


async def test_allowlist_header_needs_token(server, request_ctx, test_cfg, monkeypatch):
    monkeypatch.delenv("QA_TOOL_ALLOWLIST_TOKEN", raising=False)
    url = server + "/needs-header"
    res = (await check_urls(request_ctx, [url], allowlist_cfg(test_cfg, ["127.0.0.1"])))[url]
    assert res.outcome == "unverifiable"


# --- CSV exports ---------------------------------------------------------------------------------

def rows(text):
    return list(csv.reader(io.StringIO(text)))


def table(text, first_col):
    """The data table that follows the summary block: header row onwards."""
    r = rows(text)
    start = next(i for i, row in enumerate(r) if row and row[0] == first_col)
    return r[start:]


def test_findings_csv_starts_with_summary_block():
    r = rows(findings_csv(make_run()))
    assert r[0] == ["Page", SITE + "/p"]
    checked = r[1][1]   # local time, minutes precision, no UTC offset
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", checked), checked
    totals = dict(x[:2] for x in r if len(x) >= 2)["Totals"]
    assert "2 links" in totals and "1 to check by hand" in totals


def test_findings_csv_plain_english_columns():
    t = table(findings_csv(make_run()), "Severity")
    assert t[0] == ["Severity", "Action", "Issue", "Link text", "Link on page", "Times on page", "Suggested fix",
                    "HTTP status", "Redirect path", "Checked by", "Section", "Rule"]
    by_rule = {r["Rule"]: r for r in records(t)}
    chain_row, blocked_row = by_rule["L05"], by_rule["L02"]
    assert chain_row["Severity"] == "Major" and chain_row["Action"] == "Fix"
    assert chain_row["Redirect path"].splitlines() == [REDIRECTED + " (301)", SITE + "/mid (301)", SITE + "/new"]
    assert chain_row["Section"] == "Page content"
    assert blocked_row["Action"] == "Check by hand" and blocked_row["Checked by"] == "Tool"
    assert blocked_row["HTTP status"] == ""          # the 403 came from bot protection, not the real page
    assert by_rule["L07"]["Action"] == "Review"      # restricted reference: review/replace, not "check by hand"


def records(t):
    return [dict(zip(t[0], r)) for r in t[1:]]


def test_findings_csv_merges_repeated_links_with_count():
    run = make_run()
    dup = copy.deepcopy(run.links[1])            # the same "Old page" link appears again (e.g. in another tab)
    run.links.append(dup)
    apply_review(run, None, None, CFG)
    l05 = [r for r in records(table(findings_csv(run), "Severity")) if r["Rule"] == "L05"]
    assert len(l05) == 1 and l05[0]["Times on page"] == "2"
    summary = dict(x[:2] for x in rows(findings_csv(run)) if len(x) >= 2)
    assert summary["Issues"] == "3 major · 1 info"   # counted per occurrence: 2x L05, L07; L02
    assert summary["Scope"] == "Page content (header & footer excluded)"


def test_findings_csv_shows_reviewer_verdict():
    run = make_run()
    apply_review(run, BLOCKED, "broken", CFG)
    broken = next(r for r in records(table(findings_csv(run), "Severity")) if r["Rule"] == "L01")
    assert broken["Severity"] == "Critical" and broken["Checked by"] == "Reviewer"


def test_links_csv_readable_results():
    t = table(links_csv(make_run()), "Section")
    assert t[0] == ["Section", "Type", "Link text", "Link on page", "Opens in", "Visible",
                    "Result", "HTTP status", "Final URL", "Checked by"]
    by_text = {r["Link text"]: r for r in records(t)}
    assert {k: r["Result"] for k, r in by_text.items()} == {"Community post": "Check by hand", "Old page": "Redirect"}
    assert by_text["Old page"]["Type"] == "Internal" and by_text["Old page"]["Section"] == "Page content"
    assert by_text["Old page"]["Final URL"] == SITE + "/new"
    assert by_text["Community post"]["Final URL"] == "" and by_text["Community post"]["HTTP status"] == ""


# --- dashboard review route ----------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture(scope="module")
def run_url(server):
    r = client.post("/run", data={"url": server + "/fixtures/review_page.html"}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"]


def test_report_lists_links_needing_human_check(run_url, server):
    page = client.get(run_url).text
    assert "1 link needs a human check" in page   # /forbidden appears twice but is one row to mark
    assert server + "/forbidden" in page


def test_review_route_marks_broken_and_updates_counts(run_url, server):
    r = client.post(run_url + "/review", data={"url": server + "/forbidden", "verdict": "broken"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("#review")
    page = client.get(run_url).text
    assert "Marked broken by reviewer" in page
    client.post(run_url + "/review", data={"url": server + "/forbidden", "verdict": "reset"})


def test_review_route_rejects_bad_input(run_url, server):
    r = client.post(run_url + "/review", data={"url": server + "/ok", "verdict": "broken"})
    assert r.status_code == 400
    r = client.post(run_url + "/review", data={"url": server + "/forbidden", "verdict": "maybe"})
    assert r.status_code == 400


def test_review_route_unknown_run_404():
    assert client.post("/runs/nope/review", data={"url": "x", "verdict": "ok"}).status_code == 404


def test_empty_link_row_does_not_borrow_the_page_status():
    run = make_run()
    page = SITE + "/p"
    run.links += [LinkRecord(raw_href="#", abs_url=page + "#", text="Placeholder", target="", region="main",
                             visible=True, selector="a", bbox=None, kind="empty"),
                  LinkRecord(raw_href="/p", abs_url=page, text="This page", target="", region="main",
                             visible=True, selector="a", bbox=None, kind="internal")]
    run.results[page] = CheckResult(url=page, outcome="ok", status=200, final_url=page)
    apply_review(run, None, None, CFG)
    l09 = next(r for r in records(table(findings_csv(run), "Severity")) if r["Rule"] == "L09")
    assert l09["HTTP status"] == "" and l09["Checked by"] == "Tool"
