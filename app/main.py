"""Dashboard: enter a page URL, run the link check, read and export the report."""
import asyncio
import ipaddress
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import Error as PlaywrightError

from engine.links.classify import CHECKABLE, check_key
from engine.config import load_config
from engine.runner import apply_review, run_sync
from report.export import findings_csv, links_csv, local_time, shown_status

HERE = Path(__file__).parent
app = FastAPI(title="OpenText QA Tool", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["local_time"] = local_time
templates.env.filters["http_status"] = shown_status

# shortcut: runs live in memory and vanish on restart; move to data/runs.sqlite with the history slice.
RUNS: dict[str, dict] = {}
MAX_RUNS = 50

# Set on the public Cloud Run deploy: block internal addresses and cap daily runs. Off for local use and tests.
PUBLIC = os.environ.get("QA_TOOL_PUBLIC") == "1"
DAILY_RUN_LIMIT = 200
# shortcut: in-memory count resets when the instance restarts (exact only with max-instances 1); persist with history.
DAILY_RUNS = {"date": "", "count": 0}
# Each run starts its own Chromium (several hundred MB); more runs wait instead of exhausting memory.
RUN_SLOTS = asyncio.Semaphore(2)


def _is_public_host(host: str) -> bool:
    """False if the host is or resolves to a loopback, private, link-local (cloud metadata) or other non-public address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return True  # unresolvable: let the browser report it as "could not open"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not (getattr(ip, "ipv4_mapped", None) or ip).is_global:
            return False
    return True


def _take_daily_run() -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    if DAILY_RUNS["date"] != today:
        DAILY_RUNS.update(date=today, count=0)
    if DAILY_RUNS["count"] >= DAILY_RUN_LIMIT:
        return False
    DAILY_RUNS["count"] += 1
    return True


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/run")
async def start_run(request: Request, url: str = Form(...), include_global: bool = Form(False)):
    url = url.strip()
    form = {"url": url, "include_global": include_global}
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return templates.TemplateResponse(request, "index.html", {
            "error": "Enter a full page address starting with http:// or https://", **form}, status_code=400)
    if PUBLIC and not await asyncio.to_thread(_is_public_host, parsed.hostname or ""):
        return templates.TemplateResponse(request, "index.html", {
            "error": "Only public web pages can be checked.", **form}, status_code=400)
    if PUBLIC and not _take_daily_run():
        return templates.TemplateResponse(request, "index.html", {
            "error": f"The daily limit of {DAILY_RUN_LIMIT} checks has been reached. Please try again tomorrow.",
            **form}, status_code=429)
    try:
        # Worker thread + fresh loop: Playwright needs a subprocess-capable loop, whatever loop uvicorn runs.
        async with RUN_SLOTS:
            result = await asyncio.to_thread(run_sync, url, include_global)
    except PlaywrightError as e:
        return templates.TemplateResponse(request, "index.html", {
            "error": f"Could not open the page: {str(e).splitlines()[0]}", **form}, status_code=502)
    except ValueError as e:  # a mistake in governance/rules.yaml
        return templates.TemplateResponse(request, "index.html", {"error": str(e), **form}, status_code=500)
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"result": result}
    while len(RUNS) > MAX_RUNS:
        RUNS.pop(next(iter(RUNS)))
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


def _get(run_id: str) -> dict:
    if run_id not in RUNS:
        raise HTTPException(404, "Run not found (runs are kept until the tool restarts)")
    return RUNS[run_id]


@app.get("/runs/{run_id}")
async def report(request: Request, run_id: str):
    entry = _get(run_id)
    result = entry["result"]
    link_rows = [(l, result.results.get(check_key(l.abs_url)) if l.kind in CHECKABLE else None)
                 for l in result.links]
    # one row per URL the tool could not check (or a person already marked), with the first link text seen
    review_rows = {}
    for l, res in link_rows:
        if res and (res.outcome == "unverifiable" or res.checked_by == "reviewer"):
            review_rows.setdefault(res.url, (l.text, res))
    return templates.TemplateResponse(request, "report.html", {
        "run_id": run_id, "r": result, "link_rows": link_rows,
        "review_rows": review_rows,
        # per URL, like the table; the counters count every time a link appears
        "left": sum(res.outcome == "unverifiable" for _, res in review_rows.values())})


@app.post("/runs/{run_id}/review")
async def review(run_id: str, url: str = Form(...), verdict: str = Form(...)):
    entry = _get(run_id)
    try:
        apply_review(entry["result"], url, verdict, load_config())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/runs/{run_id}#review", status_code=303)


def _csv_response(text: str, name: str) -> Response:
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return Response("\ufeff" + text, media_type="text/csv; charset=utf-8",  # BOM so Excel reads UTF-8
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'})


@app.get("/runs/{run_id}/findings.csv")
async def findings_download(run_id: str):
    entry = _get(run_id)
    return _csv_response(findings_csv(entry["result"]), f"QA_Findings_{run_id}")


@app.get("/runs/{run_id}/links.csv")
async def links_download(run_id: str):
    entry = _get(run_id)
    return _csv_response(links_csv(entry["result"]), f"QA_Links_{run_id}")
