import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from engine.http.link_checker import check_urls


@pytest_asyncio.fixture(scope="module")
async def request_ctx():
    async with async_playwright() as p:
        ctx = await p.request.new_context()
        yield ctx
        await ctx.dispose()


async def check_one(request_ctx, url, cfg):
    return (await check_urls(request_ctx, [url], cfg))[url]


async def test_ok(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/ok", test_cfg)
    assert (r.outcome, r.status, r.chain) == ("ok", 200, [])


@pytest.mark.parametrize("path,status", [("/missing", 404), ("/gone", 410), ("/ot404", 490), ("/error", 500)])
async def test_404_410_490_500_are_broken(server, request_ctx, test_cfg, path, status):
    r = await check_one(request_ctx, server + path, test_cfg)
    assert (r.outcome, r.status) == ("broken", status)


async def test_permanent_redirect_records_chain(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/r301", test_cfg)
    assert r.outcome == "ok"
    assert r.chain == [[server + "/r301", 301]]
    assert r.final_url == server + "/ok"


async def test_chain_with_relative_location(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/chain1", test_cfg)
    assert r.outcome == "ok"
    assert [s for _, s in r.chain] == [301, 301]
    assert r.final_url == server + "/ok"


async def test_redirect_loop_is_broken(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/loop1", test_cfg)
    assert (r.outcome, r.error) == ("broken", "Redirect loop")


async def test_redirect_to_404_is_broken(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/to404", test_cfg)
    assert (r.outcome, r.status, len(r.chain)) == ("broken", 404, 1)


async def test_timeout_is_broken(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/slow", test_cfg)
    assert r.outcome == "broken"
    assert "timeout" in r.error.lower()


async def test_head_405_falls_back_to_get(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/head405", test_cfg)
    assert (r.outcome, r.status) == ("ok", 200)


async def test_403_is_unverifiable(server, request_ctx, test_cfg):
    r = await check_one(request_ctx, server + "/forbidden", test_cfg)
    assert (r.outcome, r.status) == ("unverifiable", 403)


async def test_bot_challenge_body_is_unverifiable(server, request_ctx, test_cfg):
    # HEAD is rejected, so the GET fallback runs; its 200 body is a challenge page, not the real page.
    r = await check_one(request_ctx, server + "/challenge", test_cfg)
    assert r.outcome == "unverifiable"


async def test_connection_refused_is_broken(request_ctx, test_cfg, closed_port_url):
    r = await check_one(request_ctx, closed_port_url, test_cfg)
    assert r.outcome == "broken"
    assert r.error


async def test_duplicate_urls_checked_once(server, request_ctx, test_cfg):
    res = await check_urls(request_ctx, [server + "/ok", server + "/ok"], test_cfg)
    assert list(res) == [server + "/ok"]


async def test_malformed_bot_response_is_unverifiable(request_ctx, test_cfg, malformed_http_url):
    r = await check_one(request_ctx, malformed_http_url, test_cfg)
    assert r.outcome == "unverifiable"
