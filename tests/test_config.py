import urllib.error
import urllib.request

import pytest

from engine.config import DEFAULT_PATH, load_config


def test_load_config_has_link_check_defaults():
    cfg = load_config()
    lc = cfg["link_check"]
    assert 490 in lc["broken_statuses"]
    assert "www.opentext.com" in lc["internal_hosts"]


def test_server_fixture_serves_routes(server):
    assert urllib.request.urlopen(server + "/ok").status == 200
    try:
        urllib.request.urlopen(server + "/missing")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


@pytest.mark.parametrize("old,new", [
    ("pattern: 'https?://", "pattern: '(https?://"),                              # unbalanced regex
    ("  L06: {name: Legacy video URL, severity: major, status: issue}\n", ""),   # rule removed
    ("rules:", "rules: ["),                                                    # broken YAML
    ("concurrency: 8 ", "concurrency: 0 "),                                    # would hang forever
    ("  retries: 1 ", "  # retries: 1 "),                                     # key removed
    ("timeout_ms: 15000", "timeout_ms: 15s"),                                 # not a number
    ("L01: {name: Broken link, severity: critical", "L01: {name: Broken link, severity: Critical"),
    ("restricted_references: [", "restricted_references: x #["),             # not a list
    ("allowlist_hosts: [opentext.com]", "allowlist_hosts: opentext.com"),     # token would never be sent
    ("other_hosts: [vidyard.com]", "other_hosts: vidyard.com"),               # Vidyard check would match nothing
])
def test_config_mistakes_raise_plain_error(tmp_path, old, new):
    text = DEFAULT_PATH.read_text(encoding="utf-8")
    assert old in text
    bad = tmp_path / "rules.yaml"
    bad.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError, match="rules.yaml"):
        load_config(bad)
