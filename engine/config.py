"""Loads the governance rules file that non-developers edit."""
import re
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "governance" / "rules.yaml"
RULE_IDS = [f"L0{i}" for i in range(1, 10)]
SEVERITIES = ["critical", "major", "minor", "info"]
STATUSES = ["issue", "review"]
# smallest allowed value: a semaphore of 0 waits forever, so a 0 concurrency would hang the run
NUMBERS = {"timeout_ms": 1, "retries": 0, "max_redirects": 0, "concurrency": 1, "per_host_concurrency": 1}
LISTS = ["internal_hosts", "resource_extensions", "broken_statuses", "unverifiable_statuses",
         "bot_protection_markers", "restricted_references", "allowlist_hosts"]


def load_config(path: str | Path | None = None) -> dict:
    """Raises ValueError with a plain message when the file has a mistake, so the dashboard can show it."""
    try:
        with open(path or DEFAULT_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        lc = cfg["link_check"]
        re.compile(lc["legacy_video"]["pattern"])
        lc["legacy_video"]["replacement"]   # KeyError if missing
        # a bare string here would be read letter by letter and quietly match nothing
        lists = [k for k in LISTS if not isinstance(lc[k], list)] + (
            [] if isinstance(lc["legacy_video"]["other_hosts"], list) else ["legacy_video: other_hosts"])
        numbers = [k for k, low in NUMBERS.items() if type(lc[k]) is not int or lc[k] < low]
        rules = {r: cfg["rules"].get(r) or {} for r in RULE_IDS}
        bad_rules = [r for r, v in rules.items() if v.get("severity") not in SEVERITIES or v.get("status") not in STATUSES]
    except (yaml.YAMLError, re.error, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"governance/rules.yaml has a mistake ({type(e).__name__}: {e})") from e
    if lists:
        raise ValueError(f"governance/rules.yaml: {', '.join(lists)} must be a list, e.g. [a, b]")
    if numbers:
        raise ValueError(f"governance/rules.yaml: {', '.join(numbers)} must be a whole number "
                         f"(concurrency, per_host_concurrency and timeout_ms at least 1)")
    if bad_rules:
        raise ValueError(f"governance/rules.yaml: rules {', '.join(bad_rules)} need a severity "
                         f"({', '.join(SEVERITIES)}) and a status ({' or '.join(STATUSES)}), in lower case")
    return cfg
