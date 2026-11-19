import pytest

from engine.config import load_config
from engine.links.classify import check_key, classify_link

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

