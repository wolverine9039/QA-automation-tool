"""Dashboard: enter a page URL, run the link check, read and export the report."""
import asyncio
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import Error as PlaywrightError

from engine.links.classify import CHECKABLE, check_key
from engine.runner import run_sync
from report.export import findings_csv, links_csv

HERE = Path(__file__).parent
app = FastAPI(title="OpenText QA Tool")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

# shortcut: runs live in memory and vanish on restart; move to data/runs.sqlite with the history slice.
RUNS: dict[str, dict] = {}
MAX_RUNS = 50


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/run")
async def start_run(request: Request, url: str = Form(...), ticket_id: str = Form(""),
                    include_global: bool = Form(False)):
    url = url.strip()
    form = {"url": url, "ticket_id": ticket_id, "include_global": include_global}
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return templates.TemplateResponse(request, "index.html", {
            "error": "Enter a full page address starting with http:// or https://", **form}, status_code=400)
    try:
        # Worker thread + fresh loop: Playwright needs a subprocess-capable loop, whatever loop uvicorn runs.
        result = await asyncio.to_thread(run_sync, url, include_global)
    except PlaywrightError as e:
        return templates.TemplateResponse(request, "index.html", {
            "error": f"Could not open the page: {str(e).splitlines()[0]}", **form}, status_code=502)
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"ticket_id": ticket_id.strip(), "result": result}
    while len(RUNS) > MAX_RUNS:
        RUNS.pop(next(iter(RUNS)))
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


def _get(run_id: str) -> dict:
    if run_id not in RUNS:
        raise HTTPException(404, "Run not found (runs are kept until the tool restarts)")
    return RUNS[run_id]


@app.get("/runs/{run_id}")
def report(request: Request, run_id: str):
    entry = _get(run_id)
    result = entry["result"]
    link_rows = [(l, result.results.get(check_key(l.abs_url)) if l.kind in CHECKABLE else None)
                 for l in result.links]
    return templates.TemplateResponse(request, "report.html", {
        "run_id": run_id, "ticket_id": entry["ticket_id"], "r": result, "link_rows": link_rows})


def _csv_response(text: str, name: str) -> Response:
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return Response("﻿" + text, media_type="text/csv; charset=utf-8",  # BOM so Excel reads UTF-8
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'})


@app.get("/runs/{run_id}/findings.csv")
def findings_download(run_id: str):
    entry = _get(run_id)
    return _csv_response(findings_csv(entry["result"]), f"QA_Findings_{entry['ticket_id'] or run_id}")


@app.get("/runs/{run_id}/links.csv")
def links_download(run_id: str):
    entry = _get(run_id)
    return _csv_response(links_csv(entry["result"]), f"QA_Links_{entry['ticket_id'] or run_id}")
