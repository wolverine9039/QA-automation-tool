"""Loads the governance rules file that non-developers edit."""
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "governance" / "rules.yaml"


def load_config(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)
