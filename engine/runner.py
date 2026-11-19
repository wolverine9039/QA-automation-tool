"""One QA run: load the page, extract links and embeds, check them, apply rules, summarise."""
import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from engine.config import load_config
from engine.extract.links import extract_embeds, extract_links
from engine.http.link_checker import check_urls
from engine.inventory import summarize
from engine.links.classify import CHECKABLE, check_key
from engine.load.page_loader import load_page
from engine.models import RunResult
from engine.rules.link import broken_links, governance

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
            embeds = await extract_embeds(page)
            if not include_global:
                links = [l for l in links if l.region == "main"]
                embeds = [e for e in embeds if e.region == "main"]
            to_check = [check_key(l.abs_url) for l in links if l.kind in CHECKABLE]
            # context.request shares the page's cookies, which keeps WAFs from blocking every check
            results = await check_urls(context.request, to_check, cfg)
        finally:
            await browser.close()
    result = RunResult(
        url=url, final_url=final_url, page_status=page_status, include_global=include_global,
        started_at=started_at, duration_s=round(time.monotonic() - started, 1),
        links=links, results=results, findings=[], inventory={}, embeds=embeds,
        warnings=page_warnings(url, final_url, page_status, page_html, links, cfg),
    )
    _refresh(result, cfg)
    return result


def _refresh(result: RunResult, cfg: dict) -> None:
    lc, page_host = cfg["link_check"], urlparse(result.final_url).hostname or ""
    if page_host not in lc["internal_hosts"]:
        # A relative path only works on the page's own host: on blogs.opentext.com, "/x" is not www.opentext.com/x.
        cfg = {**cfg, "link_check": {**lc, "internal_hosts": [page_host]}}
    findings = (broken_links.evaluate(result.links, result.results, cfg)
                + governance.evaluate(result.links, result.embeds, cfg))
    result.findings = sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
    result.inventory = summarize(result.links, result.results) | {
        "legacy": governance.legacy_count(result.links + result.embeds, cfg)}


VERDICTS = {"ok", "broken", "reset"}


def apply_review(result: RunResult, url: str | None, verdict: str | None, cfg: dict) -> None:
    """Record a person's verdict on a link the tool could not check, then recompute findings and counts.

    With url=None only the recompute happens. Raises ValueError for anything that is not a reviewable link.
    """
    if url is not None:
        res = result.results.get(url)
        if verdict not in VERDICTS:
            raise ValueError(f"Unknown verdict: {verdict!r}")
        if res is None or not (res.outcome == "unverifiable" or res.checked_by == "reviewer"):
            raise ValueError("Only links the tool could not check can be reviewed")
        res.status = None  # the blocked response's status says nothing about the real page
        if verdict == "reset":
            res.outcome, res.checked_by, res.error = "unverifiable", "tool", None
        else:
            res.outcome, res.checked_by = verdict, "reviewer"
            res.error = "Marked broken by reviewer" if verdict == "broken" else None
    _refresh(result, cfg)


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
