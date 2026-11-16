"""Checks each unique URL over HTTP, following redirects by hand so the full chain is visible."""
import asyncio
from urllib.parse import urljoin, urlparse

from playwright.async_api import Error as PlaywrightError

from engine.models import CheckResult

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
BODY_SNIFF_BYTES = 65536


async def check_urls(request_ctx, urls: list[str], cfg: dict) -> dict[str, CheckResult]:
    """request_ctx is a Playwright APIRequestContext (use the page's context.request to share cookies)."""
    lc = cfg["link_check"]
    global_sem = asyncio.Semaphore(lc["concurrency"])
    host_sems: dict[str, asyncio.Semaphore] = {}
    unique = list(dict.fromkeys(urls))

    async def one(url: str) -> CheckResult:
        host_sem = host_sems.setdefault(urlparse(url).hostname or "", asyncio.Semaphore(lc["per_host_concurrency"]))
        async with global_sem, host_sem:
            return await _check(request_ctx, url, lc)

    return dict(zip(unique, await asyncio.gather(*(one(u) for u in unique))))


async def _check(ctx, url: str, lc: dict) -> CheckResult:
    chain: list = []
    seen = {url}
    current = url
    for _ in range(lc["max_redirects"] + 1):
        try:
            status, location, body = await _fetch(ctx, current, lc)
        except PlaywrightError as e:
            msg = _first_line(e)
            # Bot protection (e.g. Imperva) answers automated clients with malformed HTTP.
            outcome = "unverifiable" if "Parse Error" in msg else "broken"
            return CheckResult(url, outcome, None, current, chain, msg)
        if status in REDIRECT_STATUSES and location:
            chain.append([current, status])
            nxt = urljoin(current, location)
            if nxt in seen:
                return CheckResult(url, "broken", status, nxt, chain, "Redirect loop")
            seen.add(nxt)
            current = nxt
            continue
        if body and any(m in body for m in lc["bot_protection_markers"]):
            return CheckResult(url, "unverifiable", status, current, chain, "Bot-protection challenge page")
        return CheckResult(url, _outcome(status, lc), status, current, chain)
    return CheckResult(url, "broken", None, current, chain, f"More than {lc['max_redirects']} redirects")


def _outcome(status: int, lc: dict) -> str:
    if status in lc["broken_statuses"] or status >= 500:
        return "broken"
    if status in lc["unverifiable_statuses"]:
        return "unverifiable"
    return "ok" if status < 400 else "broken"


async def _fetch(ctx, url: str, lc: dict) -> tuple[int, str | None, str]:
    """HEAD first (no body download); GET when HEAD fails or is refused, since many servers mishandle HEAD."""
    try:
        resp = await _request(ctx, url, "HEAD", lc)
        if resp.status < 400:
            result = resp.status, resp.headers.get("location"), ""
            await resp.dispose()
            return result
        await resp.dispose()
    except PlaywrightError as e:
        if "timeout" in str(e).lower():
            raise
    resp = await _request(ctx, url, "GET", lc)
    body = ""
    if resp.status < 300:
        body = (await resp.body())[:BODY_SNIFF_BYTES].decode("utf-8", "replace")
    result = resp.status, resp.headers.get("location"), body
    await resp.dispose()
    return result


async def _request(ctx, url: str, method: str, lc: dict):
    attempts = lc["retries"] + 1
    for attempt in range(attempts):
        try:
            return await ctx.fetch(url, method=method, max_redirects=0, timeout=lc["timeout_ms"])
        except PlaywrightError as e:
            if "Parse Error" in str(e) or attempt == attempts - 1:
                raise


def _first_line(e: Exception) -> str:
    return str(e).split("\n")[0].replace("APIRequestContext.fetch: ", "").strip()
