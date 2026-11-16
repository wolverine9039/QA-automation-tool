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
    target = _suggested_target(link, res)  # the suggestion is the replacement URL itself, ready to paste
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


def _suggested_target(link: LinkRecord, res: CheckResult) -> str:
    """Keep relative internal links relative, per the authoring standard."""
    authored = urlparse(link.raw_href)
    if link.kind in ("internal", "resource") and not authored.scheme and not authored.netloc:
        final = urlparse(res.final_url)
        return final.path + (f"?{final.query}" if final.query else "")
    return res.final_url


def _finding(rule_id, link, cfg, category, message, suggestion, res: CheckResult | None = None) -> Finding:
    rule = cfg["rules"][rule_id]
    return Finding(
        rule_id=rule_id, category=category, severity=rule["severity"], status=rule["status"],
        message=message, suggestion=suggestion, element_text=link.text, raw_value=link.raw_href,
        url=link.abs_url, selector=link.selector, region=link.region, bbox=link.bbox,
        http_status=res.status if res else None, chain=res.chain if res else [],
    )
