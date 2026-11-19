"""Rules L06-L08 (legacy video, restricted references, absolute internal URLs) and the Legacy counter."""
from engine.config import load_config
from engine.models import CheckResult, LinkRecord, RunResult
from engine.rules.link import broken_links
from engine.rules.link.governance import evaluate, legacy_count
from engine.runner import apply_review

CFG = load_config()
SITE = "https://www.opentext.com"


def link(raw, kind="external", abs_url=None, text="Link"):
    return LinkRecord(raw_href=raw, abs_url=abs_url or raw, text=text, target="",
                      region="main", visible=True, selector="a", bbox=None, kind=kind)


def embed(src):
    return link(src, kind="embed", text="iframe")


def by_rule(findings, rule_id):
    return [f for f in findings if f.rule_id == rule_id]


def test_legacy_vidyard_link_suggests_new_host():
    f = by_rule(evaluate([link("https://opentext.hubs.vidyard.com/watch/AbC123?t=5")], [], CFG), "L06")
    assert len(f) == 1
    assert f[0].suggestion == "https://videos.opentext.com/watch/AbC123"
    assert (f[0].severity, f[0].status) == ("major", "issue")


def test_legacy_vidyard_embed_is_flagged():
    f = by_rule(evaluate([], [embed("https://opentext.hubs.vidyard.com/watch/xyz")], CFG), "L06")
    assert len(f) == 1 and "embedded" in f[0].message
    assert f[0].suggestion == "https://videos.opentext.com/watch/xyz"


def test_other_vidyard_url_flagged_without_replacement_url():
    f = by_rule(evaluate([], [embed("//play.vidyard.com/embed/v4.js")], CFG), "L06")
    assert len(f) == 1 and "videos.opentext.com/watch/..." in f[0].suggestion


def test_new_video_host_and_lookalike_hosts_not_flagged():
    items = [link("https://videos.opentext.com/watch/abc"), link("https://notvidyard.com/x")]
    assert by_rule(evaluate(items, [], CFG), "L06") == []


def test_restricted_references_case_insensitive_review():
    items = [link("https://community.opentext.com/blog"), link("/x?from=MicroFocus", kind="internal"),
             link("/en/Solutions/Aviator", kind="internal"), embed("https://cdn.microfocus.com/p.js")]
    f = by_rule(evaluate(items[:3], items[3:], CFG), "L07")
    assert len(f) == 4
    assert {x.status for x in f} == {"review"} and {x.severity for x in f} == {"major"}


def test_empty_links_skipped():
    assert evaluate([link("", kind="empty")], [], CFG) == []


def test_absolute_internal_url_suggests_relative_path():
    l = link(SITE + "/products/example?x=1#top", kind="internal")
    f = by_rule(evaluate([l], [], CFG), "L08")
    assert len(f) == 1 and f[0].suggestion == "/products/example?x=1#top"
    assert f[0].severity == "minor"
    bare = by_rule(evaluate([link("https://opentext.com", kind="internal")], [], CFG), "L08")
    assert bare[0].suggestion == "/"


def test_relative_subdomain_and_external_links_not_L08():
    items = [link("/products/x", kind="internal", abs_url=SITE + "/products/x"),
             link("https://support.opentext.com/x"), link("https://www.linkedin.com/x"),
             link("mailto:a@opentext.com", kind="mailto")]
    assert by_rule(evaluate(items, [], CFG), "L08") == []


def test_embeds_never_get_L08():
    assert by_rule(evaluate([], [embed(SITE + "/media/player.js")], CFG), "L08") == []


def test_legacy_count_includes_links_and_embeds():
    items = [link("https://opentext.hubs.vidyard.com/watch/a"), link("https://community.opentext.com/x"),
             embed("//play.vidyard.com/x"), link("https://www.linkedin.com/x"), link("", kind="empty")]
    assert legacy_count(items, CFG) == 3


def test_absolute_internal_redirect_suggests_relative_final_url():
    l = link(SITE + "/old", kind="internal")
    r = CheckResult(url=SITE + "/old", outcome="ok", status=200, final_url=SITE + "/new", chain=[[SITE + "/old", 301]])
    f = broken_links.evaluate([l], {l.abs_url: r}, CFG)
    assert f[0].rule_id == "L03" and f[0].suggestion == "/new"


def test_page_on_other_host_gets_no_relative_suggestions():
    """On blogs.opentext.com, "/new" would point to blogs.opentext.com/new, so suggest the full URL."""
    blog = "https://blogs.opentext.com/post"
    l = link(SITE + "/old", kind="internal")
    r = CheckResult(url=SITE + "/old", outcome="ok", status=200, final_url=SITE + "/new", chain=[[SITE + "/old", 301]])
    run = RunResult(url=blog, final_url=blog, page_status=200, include_global=False, started_at="t",
                    duration_s=0, links=[l], results={l.abs_url: r}, findings=[], inventory={})
    apply_review(run, None, None, CFG)
    assert by_rule(run.findings, "L08") == []
    assert by_rule(run.findings, "L03")[0].suggestion == SITE + "/new"
    assert CFG["link_check"]["internal_hosts"] == ["www.opentext.com", "opentext.com"]   # shared config untouched


def test_full_url_to_own_sub_site_suggests_relative():
    """On blogs.opentext.com, a full blogs.opentext.com URL is classified external but should still be relative."""
    blog = "https://blogs.opentext.com/post"
    l = link("https://blogs.opentext.com/other?x=1", kind="external")
    run = RunResult(url=blog, final_url=blog, page_status=200, include_global=False, started_at="t",
                    duration_s=0, links=[l], results={}, findings=[], inventory={})
    apply_review(run, None, None, CFG)
    assert by_rule(run.findings, "L08")[0].suggestion == "/other?x=1"
