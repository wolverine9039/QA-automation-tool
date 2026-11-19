"""Rules L01-L05 and L09: turn HTTP check results into findings, one per link on the page."""
from urllib.parse import urlparse

from engine.links.classify import CHECKABLE, check_key
from engine.models import CheckResult, Finding, LinkRecord

PERMANENT = {301, 308}


def evaluate(links: list[LinkRecord], results: dict[str, CheckResult], cfg: dict) -> list[Finding]:
    findings = []
    for link in links:
        if link.kind == "empty":
            if link.role == "button" and link.raw_href.strip():
                continue  # "#" / javascript: on role=button is a JS control (e.g. modal close), not a link
            findings.append(_finding("L09", link, cfg, "Broken Link", "Empty or placeholder link",
                                     "Add the destination URL, or remove the link."))
            continue
        if link.kind not in CHECKABLE:
            continue
        res = results.get(check_key(link.abs_url))
        if res is None:
            continue
        finding = _from_result(link, res, cfg)
        if finding:
            findings.append(finding)
    return findings


def _from_result(link: LinkRecord, res: CheckResult, cfg: dict) -> Finding | None:
    if res.outcome == "broken":
        reason = res.error or f"HTTP {res.status}"
        return _finding("L01", link, cfg, "Broken Link", f"Broken link ({reason})",
                        "Fix the URL or remove the link.", res)
    if res.outcome == "unverifiable":
        return _finding("L02", link, cfg, "Broken Link",
                        "Could not verify automatically (bot protection or access restricted); check manually",
                        "Open the link in a browser to confirm it works.", res)
    hops = len(res.chain)
    if hops == 0:
        return None
    target = _suggested_target(link, res, cfg)  # the suggestion is the replacement URL itself, ready to paste
    path = " -> ".join([h[0] for h in res.chain] + [res.final_url])
    if hops > 1:
        return _finding("L05", link, cfg, "Redirect", f"Redirect chain ({hops} hops): {path}",
                        target, res)
    status = res.chain[0][1]
    if status in PERMANENT:
        return _finding("L03", link, cfg, "Redirect", f"Permanent redirect ({status}) to {res.final_url}",
                        target, res)
    return _finding("L04", link, cfg, "Redirect", f"Temporary redirect ({status}) to {res.final_url}",
                    target, res)


def _suggested_target(link: LinkRecord, res: CheckResult, cfg: dict) -> str:
    """Relative when the destination is internal (authoring standard, see L08); absolute when it leaves the site."""
    authored = urlparse(link.raw_href)
    final = urlparse(res.final_url)
    fragment = f"#{authored.fragment}" if authored.fragment and not final.fragment else ""
    same_host = final.netloc == urlparse(link.abs_url).netloc
    internal = (final.hostname or "") in cfg["link_check"]["internal_hosts"]
    if internal or (same_host and not authored.scheme and not authored.netloc):
        return relative(final) + fragment
    return res.final_url + fragment


def relative(u) -> str:
    """The path form of a parsed URL; a bare host ("https://www.opentext.com") is "/", never ""."""
    return (u.path or "/") + (f"?{u.query}" if u.query else "") + (f"#{u.fragment}" if u.fragment else "")


def _finding(rule_id, link, cfg, category, message, suggestion, res: CheckResult | None = None) -> Finding:
    rule = cfg["rules"][rule_id]
    return Finding(
        rule_id=rule_id, category=category, severity=rule["severity"], status=rule["status"],
        message=message, suggestion=suggestion, element_text=link.text, raw_value=link.raw_href,
        url=link.abs_url, selector=link.selector, region=link.region, bbox=link.bbox,
        chain=res.chain if res else [],
    )
