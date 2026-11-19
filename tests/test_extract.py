from collections import Counter

import pytest_asyncio
from playwright.async_api import async_playwright

from engine.config import load_config
from engine.extract.links import extract_links
from engine.load.page_loader import load_page

CFG = load_config()


@pytest_asyncio.fixture(scope="module")
async def links(server):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        status = await load_page(page, server + "/fixtures/links_page.html", CFG)
        assert status == 200
        yield await extract_links(page, CFG)
        await browser.close()


def by_text(links, text):
    return next(l for l in links if l.text == text)


async def test_extracts_all_links_with_regions(links):
    assert Counter(l.region for l in links) == {"header": 1, "footer": 1, "main": 12}


async def test_raw_href_preserved_vs_resolved(links, server):
    l = by_text(links, "Working link")
    assert l.raw_href == "/ok"
    assert l.abs_url == server + "/ok"
    assert l.selector == "#cta-ok"


async def test_hidden_tab_link_extracted_and_marked_invisible(links):
    l = by_text(links, "Hidden tab resource")
    assert l.visible is False
    assert by_text(links, "Working link").visible is True


async def test_image_link_text_falls_back_to_alt(links):
    assert any(l.text == "Logo" for l in links)


async def test_kinds_assigned(links):
    assert by_text(links, "Empty href").kind == "empty"
    assert by_text(links, "Email us").kind == "mailto"
    assert by_text(links, "Working link").kind == "internal"


async def test_bbox_present_for_visible_links(links):
    box = by_text(links, "Working link").bbox
    assert box and box["width"] > 0


async def test_role_captured(links):
    assert by_text(links, "close").role == "button"


async def test_section_header_and_footer_links_count_as_main(links):
    assert by_text(links, "Card header link").region == "main"
    assert by_text(links, "Card footer link").region == "main"


async def test_infinite_scroll_page_still_finishes(server):
    import asyncio
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await asyncio.wait_for(load_page(page, server + "/fixtures/infinite_scroll.html", CFG), timeout=40)
        await browser.close()


async def test_extract_embeds_reads_src_and_data_src(server):
    from engine.extract.links import extract_embeds
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await load_page(page, server + "/fixtures/embeds_page.html", CFG)
        embeds = await extract_embeds(page)
        await browser.close()
    by_src = {e.raw_href: e for e in embeds}
    assert set(by_src) == {"https://community.opentext.com/promo",
                           "https://opentext.hubs.vidyard.com/watch/abc123?autoplay=1",
                           "//play.vidyard.com/xyz", "/ok"}          # the iframe with no src is skipped
    assert by_src["https://community.opentext.com/promo"].region == "header"
    legacy = by_src["https://opentext.hubs.vidyard.com/watch/abc123?autoplay=1"]
    assert (legacy.kind, legacy.region, legacy.text, legacy.selector) == ("embed", "main", "iframe: Product demo", "#legacy-player")
    assert by_src["/ok"].abs_url == server + "/ok" and by_src["/ok"].text == "source"


async def test_svg_link_gets_a_real_url(server):
    """In <svg>, a.href is an object; the link must still be resolved and checked."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(server + "/ok")
        await page.set_content('<main><svg><a href="/missing"><text y="20">Logo</text></a></svg></main>')
        links = await extract_links(page, CFG)
        await browser.close()
    assert (links[0].abs_url, links[0].kind) == (server + "/missing", "internal")
