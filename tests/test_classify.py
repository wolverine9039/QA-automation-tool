import pytest

from engine.config import load_config
from engine.links.classify import check_key, classify_link
from engine.models import CheckResult, Finding, LinkRecord

CFG = load_config()
BASE = "https://www.opentext.com/products/page"


@pytest.mark.parametrize("raw,expected", [
    ("", "empty"),
    ("   ", "empty"),
    ("#", "empty"),
    ("javascript:void(0)", "empty"),
    ("#section", "anchor"),
    ("mailto:a@b.com", "mailto"),
    ("tel:123", "tel"),
    ("ftp://x.com/f", "other"),
    ("/en/media/ds.pdf", "resource"),
    ("https://www.opentext.com/x.PDF", "resource"),
    ("/products/x", "internal"),
    ("https://opentext.com/x", "internal"),
    ("https://www.linkedin.com/x", "external"),
    ("//cdn.example.com/x", "external"),
])
def test_classify_link(raw, expected):
    from urllib.parse import urljoin
    assert classify_link(raw, urljoin(BASE, raw), CFG) == expected


def test_check_key_strips_fragment_only():
    assert check_key("https://a.com/p?q=1#frag") == "https://a.com/p?q=1"


def test_models_to_dict_roundtrip_keys():
    link = LinkRecord(raw_href="/x", abs_url=BASE, text="t", target="", rel="", region="main",
                      visible=True, selector="a", bbox=None, kind="internal")
    res = CheckResult(url=BASE, outcome="ok", status=200, final_url=BASE, chain=[], error=None)
    f = Finding(rule_id="L01", category="Broken Link", severity="critical", status="issue",
                message="m", suggestion="s", element_text="t", raw_value="/x", url=BASE,
                selector="a", region="main", bbox=None, http_status=404, chain=[])
    assert link.to_dict()["kind"] == "internal"
    assert res.to_dict()["outcome"] == "ok"
    assert f.to_dict()["area"] == "Link QA"
