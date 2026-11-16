"""Command line: python -m engine.cli URL [--include-global] [--findings-csv F] [--links-csv F]"""
import argparse
import sys

from engine.runner import run_sync
from report.export import findings_csv, links_csv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check every link on one page.")
    ap.add_argument("url")
    ap.add_argument("--include-global", action="store_true", help="also check header and footer links")
    ap.add_argument("--findings-csv")
    ap.add_argument("--links-csv")
    args = ap.parse_args(argv)

    result = run_sync(args.url, args.include_global)
    print(f"Page: {result.final_url} (HTTP {result.page_status}), {result.duration_s}s")
    print("Inventory: " + ", ".join(f"{k}={v}" for k, v in result.inventory.items()))
    for f in result.findings:
        print(f"[{f.severity:8}] {f.rule_id} {f.message} | {f.element_text!r} -> {f.raw_value}"
              + (f" | suggest: {f.suggestion}" if f.suggestion and f.rule_id != "L01" else ""))
    for path, text in ((args.findings_csv, findings_csv), (args.links_csv, links_csv)):
        if path:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:  # BOM so Excel reads UTF-8
                fh.write(text(result))
    return 1 if any(f.severity == "critical" for f in result.findings) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
