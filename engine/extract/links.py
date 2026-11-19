"""Layer 1: collect every <a href> (including links in hidden tabs) and every embed source on the rendered page."""
from engine.links.classify import classify_link
from engine.models import LinkRecord

_HELPERS_JS = r"""
  const cssPath = el => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.body) {
      if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
      let i = 1, sib = el;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === el.tagName) i++;
      parts.unshift(el.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      el = el.parentElement;
    }
    return parts.join(' > ');
  };
  // HTML rule: <header>/<footer> are the page banner/footer only when not inside sectioning content;
  // a card or section header (e.g. inside <article>) is page content.
  const SECTIONING = 'main,article,aside,nav,section';
  const isGlobal = (a, tag) => { const el = a.closest(tag); return !!el && !el.parentElement.closest(SECTIONING); };
  const region = a => (a.closest('[role=banner]') || isGlobal(a, 'header')) ? 'header'
                    : (a.closest('[role=contentinfo]') || isGlobal(a, 'footer')) ? 'footer' : 'main';
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  // not el.href: on an <a> inside <svg> that is an object, not the URL
  const absUrl = raw => { try { return new URL(raw, document.baseURI).href; } catch (e) { return raw; } };
  const where = el => {
    const rects = el.getClientRects();
    const r = el.getBoundingClientRect();
    return {
      region: region(el),
      visible: rects.length > 0,
      selector: cssPath(el),
      bbox: rects.length ? {x: r.left + window.scrollX, y: r.top + window.scrollY,
                            width: r.width, height: r.height} : null,
    };
  };
"""

_EXTRACT_JS = "() => {" + _HELPERS_JS + r"""
  return [...document.querySelectorAll('a[href]')].map(a => {
    const img = a.querySelector('img[alt]');
    return {
      raw_href: a.getAttribute('href'),
      abs_url: absUrl(a.getAttribute('href')),
      text: clean(a.innerText) || clean(a.textContent) || clean(a.getAttribute('aria-label'))
            || clean(img && img.getAttribute('alt')),
      target: a.getAttribute('target') || '',
      role: a.getAttribute('role') || '',
      ...where(a),
    };
  });
}"""

# Media and embedded players: Vidyard and other third-party content usually arrive this way, not as links.
_EMBEDS_JS = "() => {" + _HELPERS_JS + r"""
  // No script[src]: <head> and template scripts (e.g. Vidyard's player) are not page content.
  const sel = 'iframe, video, source, audio, embed[src], object[data]';
  return [...document.querySelectorAll(sel)].flatMap(el => {
    const tag = el.tagName.toLowerCase();
    const raw = tag === 'object' ? el.getAttribute('data') : (el.getAttribute('src') || el.getAttribute('data-src'));
    if (!raw || !raw.trim()) return [];
    const title = clean(el.getAttribute('title'));
    return [{raw_href: raw, abs_url: absUrl(raw), text: title ? tag + ': ' + title : tag,
             target: '', role: '', ...where(el)}];
  });
}"""


async def extract_links(page, cfg: dict) -> list[LinkRecord]:
    links = [LinkRecord(**row) for row in await page.evaluate(_EXTRACT_JS)]
    for link in links:
        link.kind = classify_link(link.raw_href, link.abs_url, cfg)
    return links


async def extract_embeds(page) -> list[LinkRecord]:
    return [LinkRecord(**row, kind="embed") for row in await page.evaluate(_EMBEDS_JS)]
