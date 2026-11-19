"""Rules L06-L08: legacy video URLs, restricted references and absolute internal URLs (no HTTP needed)."""
import re
from urllib.parse import urlparse

from engine.models import Finding, LinkRecord
from engine.rules.link.broken_links import _finding, relative


def _legacy_video(raw: str, lc: dict) -> tuple[bool, str]:
    """(matched, suggested replacement or "")."""
    lv = lc["legacy_video"]
    m = re.search(lv["pattern"], raw, re.IGNORECASE)
    if m:
        return True, m.expand(lv["replacement"])
    host = (urlparse(raw.strip()).hostname or "").lower()   # also parses protocol-relative "//host/x"
    return any(host == h or host.endswith("." + h) for h in lv["other_hosts"]), ""


def _restricted(raw: str, lc: dict) -> str | None:
    low = raw.lower()
    return next((term for term in lc["restricted_references"] if term.lower() in low), None)


def _absolute_internal(link: LinkRecord, lc: dict) -> str | None:
    """The relative form of an internal link authored as a full https://www.opentext.com/... URL.

    No kind check: on a sub-site the page's own host is internal here, but the link was classified as external."""
    authored = urlparse(link.raw_href.strip())
    if authored.scheme not in ("http", "https") or (authored.hostname or "") not in lc["internal_hosts"]:
        return None
    return relative(authored)


def is_legacy(item: LinkRecord, cfg: dict) -> bool:
    """Counted in the inventory's "Legacy" metric: matched by L06 or L07."""
    lc = cfg["link_check"]
    return item.kind != "empty" and (_legacy_video(item.raw_href, lc)[0] or _restricted(item.raw_href, lc) is not None)


def legacy_count(items: list[LinkRecord], cfg: dict) -> int:
    return sum(is_legacy(i, cfg) for i in items)


def evaluate(links: list[LinkRecord], embeds: list[LinkRecord], cfg: dict) -> list[Finding]:
    lc = cfg["link_check"]
    findings = []
    for item in links + embeds:
        if item.kind == "empty":
            continue
        what = "embedded" if item.kind == "embed" else "link"
        matched, replacement = _legacy_video(item.raw_href, lc)
        if matched:
            if replacement:
                findings.append(_finding("L06", item, cfg, "Legacy", f"Legacy Vidyard video URL ({what})", replacement))
            else:
                findings.append(_finding("L06", item, cfg, "Legacy",
                                         f"Vidyard URL ({what}); confirm it uses the current videos.opentext.com link",
                                         "Replace with the matching https://videos.opentext.com/watch/... URL."))
        term = _restricted(item.raw_href, lc)
        if term:
            findings.append(_finding("L07", item, cfg, "Restricted", f"Restricted reference ({what}): contains \"{term}\"",
                                     "Replace or remove according to current standards."))
        if item.kind != "embed":
            relative = _absolute_internal(item, lc)
            if relative:
                findings.append(_finding("L08", item, cfg, "Relative URL",
                                         "Internal link uses a full URL; use a relative path", relative))
    return findings
