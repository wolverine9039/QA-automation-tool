"""One QA run: load the page, extract links, check them, apply rules, summarise."""
import asyncio
import time
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from engine.config import load_config
from engine.extract.links import extract_links
from engine.http.link_checker import check_urls
from engine.inventory import summarize
from engine.links.classify import CHECKABLE, check_key
from engine.load.page_loader import load_page
from engine.models import RunResult
from engine.rules.link.broken_links import evaluate

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


async def run(url: str, include_global: bool = False, cfg: dict | None = None) -> RunResult:
    cfg = cfg or load_config()
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            page_status = await load_page(page, url, cfg)
            final_url = page.url
            page_html = await page.content()
            links = await extract_links(page, cfg)
            if not include_global:
                links = [l for l in links if l.region == "main"]
            to_check = [check_key(l.abs_url) for l in links if l.kind in CHECKABLE]
            # context.request shares the page's cookies, which keeps WAFs from blocking every check
            results = await check_urls(context.request, to_check, cfg)
        finally:
            await browser.close()
    findings = sorted(evaluate(links, results, cfg), key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
    return RunResult(
        url=url, final_url=final_url, page_status=page_status, include_global=include_global,
        started_at=started_at, duration_s=round(time.monotonic() - started, 1),
        links=links, results=results, findings=findings, inventory=summarize(links, results),
        warnings=page_warnings(url, final_url, page_status, page_html, links, cfg),
    )


def page_warnings(url, final_url, page_status, page_html, links, cfg) -> list[str]:
    """Reasons an empty or clean report may not mean the real page is clean."""
    warnings = []
    if page_status and page_status >= 400:
        warnings.append(f"The page itself returned HTTP {page_status}, so this is probably not the page you meant to check.")
    if any(m in page_html for m in cfg["link_check"]["bot_protection_markers"]):
        warnings.append("The page looks like a bot-protection challenge, not the real page. Check it by hand.")
    if url.rstrip("/") != final_url.rstrip("/"):
        warnings.append(f"The page redirected to {final_url}.")
    if not links:
        warnings.append("No links were found in the page content. The page may not have loaded correctly.")
    return warnings


def run_sync(url: str, include_global: bool = False, cfg: dict | None = None) -> RunResult:
    """Run on a fresh event loop in this thread (Playwright needs a subprocess-capable loop on Windows)."""
    return asyncio.run(run(url, include_global, cfg))
