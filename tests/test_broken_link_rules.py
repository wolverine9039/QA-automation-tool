from engine.config import load_config
from engine.inventory import summarize
from engine.models import CheckResult, LinkRecord
from engine.rules.link.broken_links import evaluate

CFG = load_config()
SITE = "https://www.opentext.com"


def link(raw, kind, abs_url=None, text="Link", role=""):
    return LinkRecord(raw_href=raw, abs_url=abs_url or SITE + raw, text=text, target="", rel="",
                      region="main", visible=True, selector="a", bbox=None, kind=kind, role=role)


def result(url, outcome, status, chain=(), final=None, error=None):
    return CheckResult(url=url, outcome=outcome, status=status, final_url=final or url,
                       chain=[list(h) for h in chain], error=error)


def rule_ids(findings):
    return [f.rule_id for f in findings]


def test_empty_link_is_L09():
    f = evaluate([link("", "empty", abs_url=SITE + "/page")], {}, CFG)
    assert rule_ids(f) == ["L09"]
    assert f[0].severity == "major"


def test_broken_is_L01_critical():
    l = link("/gone", "internal")
    f = evaluate([l], {l.abs_url: result(l.abs_url, "broken", 490)}, CFG)
    assert rule_ids(f) == ["L01"]
    assert (f[0].severity, f[0].status, f[0].http_status) == ("critical", "issue", 490)
    assert "490" in f[0].message


def test_broken_with_error_message_uses_error():
    l = link("https://nope.example/", "external", abs_url="https://nope.example/")
    f = evaluate([l], {l.abs_url: result(l.abs_url, "broken", None, error="Timeout 15000ms exceeded.")}, CFG)
    assert "Timeout" in f[0].message


def test_unverifiable_is_L02_review():
    l = link("https://community.opentext.com/x", "external", abs_url="https://community.opentext.com/x")
    f = evaluate([l], {l.abs_url: result(l.abs_url, "unverifiable", None)}, CFG)
    assert rule_ids(f) == ["L02"]
    assert (f[0].severity, f[0].status) == ("info", "review")


def test_single_301_is_L03_with_relative_suggestion():
    l = link("/products/old/", "internal")
    r = result(l.abs_url, "ok", 200, chain=[(l.abs_url, 301)], final=SITE + "/products/old?x=1")
    f = evaluate([l], {l.abs_url: r}, CFG)
    assert rule_ids(f) == ["L03"]
    assert f[0].severity == "minor"
    assert f[0].suggestion == "/products/old?x=1"


def test_absolute_link_redirect_suggests_absolute_final_url():
    l = link("https://www.linkedin.com/a", "external", abs_url="https://www.linkedin.com/a")
    r = result(l.abs_url, "ok", 200, chain=[(l.abs_url, 308)], final="https://www.linkedin.com/b")
    assert evaluate([l], {l.abs_url: r}, CFG)[0].suggestion == "https://www.linkedin.com/b"


def test_302_is_L04():
    l = link("/promo", "internal")
    r = result(l.abs_url, "ok", 200, chain=[(l.abs_url, 302)], final=SITE + "/promo-2026")
    f = evaluate([l], {l.abs_url: r}, CFG)
    assert rule_ids(f) == ["L04"]
    assert f[0].severity == "info"


def test_chain_is_L05_only():
    l = link("/a", "internal")
    r = result(l.abs_url, "ok", 200, chain=[(l.abs_url, 301), (SITE + "/b", 301)], final=SITE + "/c")
    f = evaluate([l], {l.abs_url: r}, CFG)
    assert rule_ids(f) == ["L05"]
    assert "/b" in f[0].message


def test_fragment_link_uses_fragmentless_result():
    l = link("/ok#details", "internal")
    key = SITE + "/ok"
    f = evaluate([l], {key: result(key, "broken", 404)}, CFG)
    assert rule_ids(f) == ["L01"]


def test_ok_link_has_no_findings():
    l = link("/ok", "internal")
    assert evaluate([l], {l.abs_url: result(l.abs_url, "ok", 200)}, CFG) == []


def test_mailto_not_checked_no_findings():
    assert evaluate([link("mailto:a@b.com", "mailto", abs_url="mailto:a@b.com")], {}, CFG) == []


def test_summarize_counts():
    links = [
        link("/ok", "internal"), link("/r", "internal"), link("/x.pdf", "resource"),
        link("https://ext.com/", "external", abs_url="https://ext.com/"),
        link("https://blocked.com/", "external", abs_url="https://blocked.com/"),
        link("mailto:a@b.com", "mailto", abs_url="mailto:a@b.com"), link("", "empty", abs_url=SITE + "/"),
    ]
    results = {
        SITE + "/ok": result(SITE + "/ok", "ok", 200),
        SITE + "/r": result(SITE + "/r", "ok", 200, chain=[(SITE + "/r", 301)]),
        SITE + "/x.pdf": result(SITE + "/x.pdf", "broken", 404),
        "https://ext.com/": result("https://ext.com/", "ok", 200),
        "https://blocked.com/": result("https://blocked.com/", "unverifiable", 403),
    }
    assert summarize(links, results) == {
        "total": 7, "internal": 2, "external": 2, "resource": 1, "other": 2,
        "broken": 1, "redirected": 1, "unverifiable": 1,
    }


def test_placeholder_with_role_button_is_not_L09():
    # e.g. modal close controls: <a href="#" role="button" aria-label="close">
    assert evaluate([link("#", "empty", abs_url=SITE + "/#", role="button")], {}, CFG) == []
    assert evaluate([link("javascript:void(0)", "empty", abs_url="javascript:void(0)", role="button")], {}, CFG) == []


def test_empty_href_with_role_button_is_still_L09():
    assert rule_ids(evaluate([link("", "empty", abs_url=SITE + "/", role="button")], {}, CFG)) == ["L09"]
