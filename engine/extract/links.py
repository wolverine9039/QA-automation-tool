"""Layer 1: collect every <a href> on the rendered page, including links in hidden tabs."""
from engine.links.classify import classify_link
from engine.models import LinkRecord

_EXTRACT_JS = r"""() => {
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
  return [...document.querySelectorAll('a[href]')].map(a => {
    const img = a.querySelector('img[alt]');
    const rects = a.getClientRects();
    const r = a.getBoundingClientRect();
    return {
      raw_href: a.getAttribute('href'),
      abs_url: a.href,
      text: clean(a.innerText) || clean(a.textContent) || clean(a.getAttribute('aria-label'))
            || clean(img && img.getAttribute('alt')),
      target: a.getAttribute('target') || '',
      rel: a.getAttribute('rel') || '',
      role: a.getAttribute('role') || '',
      region: region(a),
      visible: rects.length > 0,
      selector: cssPath(a),
      bbox: rects.length ? {x: r.left + window.scrollX, y: r.top + window.scrollY,
                            width: r.width, height: r.height} : null,
    };
  });
}"""


async def extract_links(page, cfg: dict) -> list[LinkRecord]:
    links = [LinkRecord(**row) for row in await page.evaluate(_EXTRACT_JS)]
    for link in links:
        link.kind = classify_link(link.raw_href, link.abs_url, cfg)
    return links
