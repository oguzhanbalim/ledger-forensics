"""Command line: audit a payments CSV, or generate a labelled synthetic one."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from .audit import format_report, run_audit
from .detectors import Config
from .ledger import load_csv
from .synth import generate, write_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledger-forensics", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="run every check on a CSV")
    audit.add_argument("csv")
    audit.add_argument("--threshold", type=Decimal, help="approval threshold for split/just-below")
    audit.add_argument("--decimal-comma", action="store_true", help="amounts like 1.234,56")
    audit.add_argument("--weekend", default="5,6", help="weekday numbers, Monday=0 (default 5,6)")
    audit.add_argument("--json", action="store_true")
    audit.add_argument("--max-per-rule", type=int, default=5)

    gen = sub.add_parser("generate", help="write a seeded synthetic ledger with labels")
    gen.add_argument("csv")
    gen.add_argument("--seed", type=int, default=1)

    args = parser.parse_args(argv)
    if args.command == "generate":
        rows = generate(args.seed)
        write_csv(rows, args.csv)
        print(f"wrote {len(rows)} rows to {args.csv} (seed {args.seed}), synthetic")
        return 0

    loaded = load_csv(args.csv, decimal_comma=args.decimal_comma)
    for rejected in loaded.rejected:
        print(f"rejected line {rejected.line}: {rejected.reason}", file=sys.stderr)
    weekend = frozenset(int(d) for d in args.weekend.split(","))
    config = Config(approval_threshold=args.threshold, weekend_days=weekend)
    report = run_audit(loaded.entries, config)
    if args.json:
        print(json.dumps(report.to_dict(), default=str, ensure_ascii=False, indent=2))
    else:
        print(format_report(report, max_per_rule=args.max_per_rule))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
