from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_renders_form():
    r = client.get("/")
    assert r.status_code == 200
    assert 'name="url"' in r.text and 'name="ticket_id"' in r.text


def test_run_rejects_non_http_url():
    r = client.post("/run", data={"url": "file:///C:/Windows/win.ini"})
    assert r.status_code == 400
    assert "http" in r.text.lower()


def test_run_unreachable_page_shows_error(closed_port_url):
    r = client.post("/run", data={"url": closed_port_url})
    assert r.status_code == 502
    assert "could not open" in r.text.lower()


def test_run_and_report_end_to_end(server):
    r = client.post("/run", data={"url": server + "/fixtures/links_page.html", "ticket_id": "QA-123"},
                    follow_redirects=False)
    assert r.status_code == 303
    report_url = r.headers["location"]
    page = client.get(report_url)
    assert page.status_code == 200
    assert "QA-123" in page.text
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
