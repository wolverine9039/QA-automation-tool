"""Opens a page the way a visitor would, so JavaScript-rendered and lazy content is present."""
from playwright.async_api import TimeoutError as PlaywrightTimeout

NAV_TIMEOUT_MS = 60000
IDLE_TIMEOUT_MS = 15000
MAX_SCROLL_STEPS = 60  # about 60 screens; long product pages are 15-25


async def load_page(page, url: str, cfg: dict) -> int | None:
    response = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    try:
        await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
    except PlaywrightTimeout:
        pass  # pages with analytics beacons never go fully idle; the DOM is ready anyway
    # Scroll one viewport at a time so lazy-loaded sections render, then return to the top.
    # Capped, because infinite-scroll pages grow forever.
    await page.evaluate("""async (maxSteps) => {
        const step = window.innerHeight || 800;
        for (let y = 0, i = 0; y < document.body.scrollHeight && i < maxSteps; y += step, i++) {
            window.scrollTo(0, y);
            await new Promise(r => setTimeout(r, 100));
        }
        window.scrollTo(0, 0);
    }""", MAX_SCROLL_STEPS)
    return response.status if response else None
