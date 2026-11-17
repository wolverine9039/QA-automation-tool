"""CSV exports for QA tickets: a short summary block, then a table with plain-English columns."""
import csv
import io
from datetime import datetime

from engine.links.classify import CHECKABLE, check_key
from engine.models import CheckResult, RunResult

FINDING_COLUMNS = ["Severity", "Action", "Issue", "Link text", "Link on page", "Suggested fix",
                   "HTTP status", "Redirect path", "Checked by", "Section", "Rule"]
LINK_COLUMNS = ["Section", "Type", "Link text", "Link on page", "Opens in", "Visible",
                "Result", "HTTP status", "Final URL", "Checked by"]


def _safe(value) -> str:
    """Stop spreadsheet apps from running page text as a formula."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def local_time(iso: str) -> str:
    """Run times are stored in UTC; people read them in their own time zone."""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def totals_line(inv: dict) -> str:
    return (f"{inv.get('total', 0)} links · {inv.get('broken', 0)} broken · "
            f"{inv.get('redirected', 0)} redirected · {inv.get('unverifiable', 0)} to check by hand")


def _csv(run: RunResult, ticket_id: str, header: list[str], rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    summary = [["QA report", ticket_id], ["Page", run.final_url], ["Checked", local_time(run.started_at)],
               ["Totals", totals_line(run.inventory)]]
    summary += [["Warning", msg] for msg in run.warnings]
    for row in summary + [[]] + [header]:
        w.writerow([_safe(v) for v in row])
    for row in rows:
        w.writerow([_safe(v) for v in row])
    return buf.getvalue()


def _result_for(run: RunResult, url: str, kind: str = "internal") -> CheckResult | None:
    return run.results.get(check_key(url)) if kind in CHECKABLE else None


def _action(f) -> str:
    if f.status == "review":
        return "Check by hand"
    return "Review" if f.severity == "info" else "Fix"


def findings_csv(run: RunResult, ticket_id: str = "") -> str:
    def row(f):
        res = _result_for(run, f.url)
        # one hop per line, ending at the final URL; Excel shows the line breaks inside the cell
        path = "\n".join([f"{u} ({s})" for u, s in f.chain] + ([res.final_url] if res and f.chain else []))
        return [f.severity.capitalize(), _action(f), f.message, f.element_text, f.raw_value, f.suggestion,
                f.http_status or "", path, (res.checked_by if res else "tool").capitalize(), f.region, f.rule_id]
    return _csv(run, ticket_id, FINDING_COLUMNS, (row(f) for f in run.findings))


def _link_result(res: CheckResult | None) -> str:
    if res is None:
        return "Not checked"
    if res.outcome == "unverifiable":
        return "Check by hand"
    if res.outcome == "broken":
        return "Broken"
    return "Redirect" if res.chain else "Working"


def links_csv(run: RunResult, ticket_id: str = "") -> str:
    def row(l):
        res = _result_for(run, l.abs_url, l.kind)
        return [l.region, l.kind, l.text, l.raw_href, "New tab" if l.target == "_blank" else "Same tab",
                "Yes" if l.visible else "Hidden", _link_result(res), res.status if res and res.status else "",
                res.final_url if res else "", res.checked_by.capitalize() if res else ""]
    return _csv(run, ticket_id, LINK_COLUMNS, (row(l) for l in run.links))
