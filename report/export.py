"""CSV exports of findings and the full link inventory."""
import csv
import io

from engine.links.classify import CHECKABLE, check_key
from engine.models import RunResult

FINDING_COLUMNS = ["Severity", "Status", "Rule", "Category", "Message", "Suggestion", "Link text",
                   "Href", "URL", "HTTP status", "Redirect chain", "Region", "Selector"]
LINK_COLUMNS = ["Region", "Kind", "Text", "Href", "Resolved URL", "Target", "Visible",
                "Outcome", "HTTP status", "Final URL"]


def _safe(value) -> str:
    """Stop spreadsheet apps from running page text as a formula."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _csv(header: list[str], rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for row in rows:
        w.writerow([_safe(v) for v in row])
    return buf.getvalue()


def findings_csv(run: RunResult) -> str:
    return _csv(FINDING_COLUMNS, (
        [f.severity, f.status, f.rule_id, f.category, f.message, f.suggestion, f.element_text,
         f.raw_value, f.url, f.http_status, " -> ".join(f"{u} ({s})" for u, s in f.chain),
         f.region, f.selector]
        for f in run.findings))


def links_csv(run: RunResult) -> str:
    def row(l):
        res = run.results.get(check_key(l.abs_url)) if l.kind in CHECKABLE else None
        return [l.region, l.kind, l.text, l.raw_href, l.abs_url, l.target, "yes" if l.visible else "no",
                res.outcome if res else "not checked", res.status if res else "", res.final_url if res else ""]
    return _csv(LINK_COLUMNS, (row(l) for l in run.links))
