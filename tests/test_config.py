import urllib.error
import urllib.request

from engine.config import load_config


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
