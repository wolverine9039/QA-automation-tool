import csv
import io
from collections import Counter

import pytest

from engine.models import Finding, RunResult
from engine.runner import run
from report.export import findings_csv, links_csv


@pytest.fixture(scope="module")
def fixture_url(server):
    return server + "/fixtures/links_page.html"


async def test_run_main_scope(fixture_url, test_cfg):
    result = await run(fixture_url, cfg=test_cfg)
    assert result.page_status == 200
    assert {l.region for l in result.links} == {"main"}
    assert result.inventory["total"] == 12
    ids = Counter(f.rule_id for f in result.findings)
    assert ids == {"L01": 2, "L03": 1, "L09": 2}
    broken = {f.raw_value for f in result.findings if f.rule_id == "L01"}
    assert broken == {"/missing", "/gone"}
    # most serious first
    assert result.findings[0].severity == "critical"
    assert result.warnings == []


async def test_run_include_global_adds_header_footer(fixture_url, test_cfg):
    result = await run(fixture_url, include_global=True, cfg=test_cfg)
    assert result.inventory["total"] == 14
    assert Counter(f.rule_id for f in result.findings)["L01"] == 3


async def test_csv_exports_have_headers_and_rows(fixture_url, test_cfg):
    result = await run(fixture_url, cfg=test_cfg)
    rows = list(csv.reader(io.StringIO(findings_csv(result))))
    header = next(i for i, r in enumerate(rows) if r and r[0] == "Severity")
    assert len(rows) - header - 1 == len(result.findings)
    links = list(csv.reader(io.StringIO(links_csv(result))))
    header = next(i for i, r in enumerate(links) if r and r[0] == "Section")
    assert len(links) - header - 1 == len(result.links)


def test_csv_neutralises_formula_cells():
    f = Finding(rule_id="L01", category="Broken Link", severity="critical", status="issue",
                message="m", suggestion="s", element_text='=HYPERLINK("http://evil")', raw_value="/x",
                url="u", selector="a", region="main", bbox=None)
    run_result = RunResult(url="u", final_url="u", page_status=200, include_global=False,
                           started_at="t", duration_s=0, links=[], results={}, findings=[f], inventory={})
    rows = list(csv.reader(io.StringIO(findings_csv(run_result))))
    data = rows[next(i for i, r in enumerate(rows) if r and r[0] == "Severity") + 1]
    assert data[3].startswith("'=")   # Link text column


async def test_page_that_did_not_load_warns(server, test_cfg):
    result = await run(server + "/missing", cfg=test_cfg)
    text = " ".join(result.warnings)
    assert "HTTP 404" in text
    assert "No links" in text


async def test_challenge_page_warns(server, test_cfg):
    result = await run(server + "/challenge", cfg=test_cfg)
    assert any("bot-protection" in w for w in result.warnings)


async def test_page_redirect_warns(server, test_cfg):
    result = await run(server + "/r301", cfg=test_cfg)
    assert any("redirected to" in w and w.rstrip(".").endswith("/ok") for w in result.warnings)
