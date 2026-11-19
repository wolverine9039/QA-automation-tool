"""CSV exports: a short summary block, then a table with plain-English columns."""
import csv
import io
from collections import Counter
from datetime import datetime

from engine.config import SEVERITIES
from engine.links.classify import CHECKABLE, check_key
from engine.models import CheckResult, RunResult

FINDING_COLUMNS = ["Severity", "Action", "Issue", "Link text", "Link on page", "Times on page", "Suggested fix",
                   "HTTP status", "Redirect path", "Checked by", "Section", "Rule"]
LINK_COLUMNS = ["Section", "Type", "Link text", "Link on page", "Opens in", "Visible",
                "Result", "HTTP status", "Final URL", "Checked by"]
SECTIONS = {"main": "Page content", "header": "Header", "footer": "Footer"}
KINDS = {"internal": "Internal", "external": "External", "resource": "Resource (file)",
         "anchor": "Anchor (same page)", "mailto": "Email", "tel": "Phone", "empty": "Empty",
         "other": "Other", "embed": "Embed"}


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
            f"{inv.get('redirected', 0)} redirected · {inv.get('legacy', 0)} legacy · "
            f"{inv.get('unverifiable', 0)} to check by hand")


def issues_line(findings) -> str:
    counts = Counter(f.severity for f in findings)
    return " · ".join(f"{counts[s]} {s}" for s in SEVERITIES if counts[s]) or "None"


def _csv(run: RunResult, header: list[str], rows, extra_summary=()) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    scope = "Whole page" if run.include_global else "Page content (header & footer excluded)"
    summary = [["Page", run.final_url], ["Checked", local_time(run.started_at)], ["Scope", scope],
               ["Totals", totals_line(run.inventory)], *extra_summary]
    summary += [["Warning", msg] for msg in run.warnings]
    for row in summary + [[]] + [header]:
        w.writerow([_safe(v) for v in row])
    for row in rows:
        w.writerow([_safe(v) for v in row])
    return buf.getvalue()


def _result_for(run: RunResult, url: str, kind: str = "internal") -> CheckResult | None:
    return run.results.get(check_key(url)) if kind in CHECKABLE else None


def _action(f) -> str:
    if f.rule_id == "L02":
        return "Check by hand"
    return "Review" if f.status == "review" or f.severity == "info" else "Fix"


def shown_status(res: CheckResult | None) -> int | str:
    """A blocked response's status (often 200 for a challenge page) says nothing about the real page."""
    return res.status if res and res.status and res.outcome != "unverifiable" else ""


def findings_csv(run: RunResult) -> str:
    def row(f):
        res = _result_for(run, f.url) if f.rule_id != "L09" else None   # "#" resolves to the page itself
        # one hop per line, ending at the final URL; Excel shows the line breaks inside the cell
        path = "\n".join([f"{u} ({s})" for u, s in f.chain] + ([res.final_url] if res and f.chain else []))
        return (f.severity.capitalize(), _action(f), f.message, f.element_text or "(no text)", f.raw_value or "(empty)",
                f.suggestion, shown_status(res), path, (res.checked_by if res else "tool").capitalize(),
                SECTIONS.get(f.region, f.region), f.rule_id)
    # The same link often repeats on a page (tabs, carousels): one row per distinct issue, with a count.
    counts = Counter(row(f) for f in run.findings)
    rows = [[*r[:5], n, *r[5:]] for r, n in counts.items()]
    return _csv(run, FINDING_COLUMNS, rows, [["Issues", issues_line(run.findings)]])


def _link_result(res: CheckResult | None) -> str:
    if res is None:
        return "Not checked"
    if res.outcome == "unverifiable":
        return "Check by hand"
    if res.outcome == "broken":
        return "Broken"
    return "Redirect" if res.chain else "Working"


def links_csv(run: RunResult) -> str:
    def row(l):
        res = _result_for(run, l.abs_url, l.kind)
        final = res.final_url if res and res.final_url != check_key(l.abs_url) else ""   # only when it differs
        return [SECTIONS.get(l.region, l.region), KINDS.get(l.kind, l.kind), l.text or "(no text)",
                l.raw_href or "(empty)", "New tab" if l.target == "_blank" else "Same tab",
                "Yes" if l.visible else "Hidden", _link_result(res), shown_status(res), final,
                res.checked_by.capitalize() if res else ""]
    return _csv(run, LINK_COLUMNS, (row(l) for l in run.links))
