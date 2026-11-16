"""Link inventory counts for the Link QA header."""
from collections import Counter

from engine.links.classify import CHECKABLE, check_key
from engine.models import CheckResult, LinkRecord


def summarize(links: list[LinkRecord], results: dict[str, CheckResult]) -> dict:
    kinds = Counter(l.kind for l in links)
    outcomes = Counter()
    for l in links:
        res = results.get(check_key(l.abs_url)) if l.kind in CHECKABLE else None
        if res:
            outcomes[res.outcome] += 1
            outcomes["redirected"] += bool(res.chain)
    return {
        "total": len(links),
        "internal": kinds["internal"],
        "external": kinds["external"],
        "resource": kinds["resource"],
        "other": len(links) - kinds["internal"] - kinds["external"] - kinds["resource"],
        "broken": outcomes["broken"],
        "redirected": outcomes["redirected"],
        "unverifiable": outcomes["unverifiable"],
    }
