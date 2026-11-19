"""Data shapes shared by every layer: extraction, checks, rules, report."""
from dataclasses import dataclass, field


@dataclass
class LinkRecord:
    raw_href: str          # exactly as authored (getAttribute), not browser-resolved
    abs_url: str           # resolved against the page URL
    text: str
    target: str
    region: str            # header | main | footer
    visible: bool
    selector: str
    bbox: dict | None
    kind: str = ""         # see engine.links.classify; "embed" for media/iframe/script sources
    role: str = ""         # ARIA role; "button" means a JS control styled as a link


@dataclass
class CheckResult:
    url: str
    outcome: str           # ok | broken | unverifiable
    status: int | None
    final_url: str
    chain: list = field(default_factory=list)   # [[url, status], ...] redirect hops before final
    error: str | None = None
    checked_by: str = "tool"   # "reviewer" once a person has marked a link the tool could not check


@dataclass
class Finding:
    rule_id: str
    category: str
    severity: str          # critical | major | minor | info
    status: str            # issue | review
    message: str
    suggestion: str
    element_text: str
    raw_value: str
    url: str
    selector: str
    region: str
    bbox: dict | None
    chain: list = field(default_factory=list)
    area: str = "Link QA"


@dataclass
class RunResult:
    url: str
    final_url: str
    page_status: int | None
    include_global: bool
    started_at: str
    duration_s: float
    links: list[LinkRecord]
    results: dict[str, CheckResult]
    findings: list[Finding]
    inventory: dict
    warnings: list[str] = field(default_factory=list)   # reasons the results may not reflect the real page
    embeds: list[LinkRecord] = field(default_factory=list)   # iframe/script/video/... sources, kind "embed"
