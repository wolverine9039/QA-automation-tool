import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_renders_form():
    r = client.get("/")
    assert r.status_code == 200
    assert 'name="url"' in r.text and 'name="ticket_id"' not in r.text


def test_run_rejects_non_http_url():
    r = client.post("/run", data={"url": "file:///C:/Windows/win.ini"})
    assert r.status_code == 400
    assert "http" in r.text.lower()


def test_run_unreachable_page_shows_error(closed_port_url):
    r = client.post("/run", data={"url": closed_port_url})
    assert r.status_code == 502
    assert "could not open" in r.text.lower()


def test_run_and_report_end_to_end(server):
    r = client.post("/run", data={"url": server + "/fixtures/links_page.html"},
                    follow_redirects=False)
    assert r.status_code == 303
    report_url = r.headers["location"]
    page = client.get(report_url)
    assert page.status_code == 200
    assert "Broken link" in page.text
    assert "Hidden tab resource" in page.text          # full inventory is listed
    csv_resp = client.get(report_url + "/findings.csv")
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert client.get(report_url + "/links.csv").status_code == 200


def test_link_text_is_html_escaped(server):
    r = client.post("/run", data={"url": server + "/fixtures/xss_page.html"}, follow_redirects=True)
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_unknown_run_404():
    assert client.get("/runs/does-not-exist").status_code == 404


def test_report_shows_warning_instead_of_all_clear(server):
    r = client.post("/run", data={"url": server + "/missing"}, follow_redirects=True)
    assert r.status_code == 200
    assert "HTTP 404" in r.text
    assert "No broken links" not in r.text


def test_config_mistake_shows_message_not_500_page(monkeypatch):
    def broken_config(*a):
        raise ValueError("governance/rules.yaml has a mistake (KeyError: 'rules')")
    monkeypatch.setattr("app.main.run_sync", broken_config)
    r = client.post("/run", data={"url": "https://www.opentext.com/x"})
    assert r.status_code == 500 and "rules.yaml has a mistake" in r.text


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/", "http://localhost/", "http://169.254.169.254/computeMetadata/v1/",
                                 "http://[::1]/", "http://10.0.0.5/"])
def test_public_mode_blocks_internal_addresses(monkeypatch, url):
    monkeypatch.setattr("app.main.PUBLIC", True)
    monkeypatch.setattr("app.main.run_sync", lambda *a: pytest.fail("browser must not start"))
    r = client.post("/run", data={"url": url})
    assert r.status_code == 400 and "Only public web pages" in r.text


def test_public_mode_counts_runs_and_stops_at_daily_limit(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "PUBLIC", True)
    monkeypatch.setattr(main, "_is_public_host", lambda host: True)
    monkeypatch.setattr(main, "DAILY_RUNS", {"date": "", "count": 0})
    def fake_run(*a):
        raise ValueError("stop here")
    monkeypatch.setattr(main, "run_sync", fake_run)
    assert client.post("/run", data={"url": "https://www.opentext.com/x"}).status_code == 500
    assert main.DAILY_RUNS["count"] == 1
    main.DAILY_RUNS["count"] = main.DAILY_RUN_LIMIT
    r = client.post("/run", data={"url": "https://www.opentext.com/x"})
    assert r.status_code == 429 and "daily limit" in r.text


def test_api_docs_are_not_served():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
