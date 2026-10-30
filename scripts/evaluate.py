"""Precision and recall of each rule against the generator's labels, over many seeds.

The same author wrote the generator and the detectors. These numbers show the rules behave
as designed on data shaped by the same assumptions; they do not predict results on a real
ledger. Run: python scripts/evaluate.py [--seeds 20]
"""

from __future__ import annotations

import argparse
from collections import Counter

from ledger_forensics.audit import run_audit
from ledger_forensics.benford import benford_test
from ledger_forensics.detectors import Config
from ledger_forensics.synth import SynthConfig, generate

RULES = ("duplicate", "split", "just_below", "round", "weekend")


def evaluate_rules(seeds: range) -> dict[str, Counter]:
    totals: dict[str, Counter] = {rule: Counter() for rule in RULES}
    for seed in seeds:
        rows = generate(seed)
        report = run_audit(
            [r.to_entry() for r in rows], Config(approval_threshold=SynthConfig().threshold)
        )
        for rule in RULES:
            labelled = {r.entry_id for r in rows if rule in r.labels}
            flagged = report.flagged_ids(rule)
            totals[rule]["tp"] += len(flagged & labelled)
            totals[rule]["fp"] += len(flagged - labelled)
            totals[rule]["fn"] += len(labelled - flagged)
    return totals


def evaluate_benford(
    seeds: range, fractions: list[float]
) -> list[tuple[float, int, int, float, float]]:
    """How often the first-digit test flags ledgers with a share of fabricated amounts."""
    results = []
    for fraction in fractions:
        config = SynthConfig(
            duplicates=0, splits=0, just_below=0, round_vendors=0, weekend_fraud=0,
            fabricate_fraction=fraction,
        )
        flags = 0
        chi2_only = 0
        mads = []
        ps = []
        for seed in seeds:
            result = benford_test(r.amount for r in generate(seed, config))
            flags += result.flagged()
            chi2_only += result.p_value < 0.01
            mads.append(result.mad)
            ps.append(result.p_value)
        median_p = sorted(ps)[len(ps) // 2]
        results.append((fraction, chi2_only, flags, sum(mads) / len(mads), median_p))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    args = parser.parse_args()
    seeds = range(1, args.seeds + 1)

    print(f"Synthetic ledgers, seeds 1-{args.seeds}, about 2250 rows each. Entry-level counts.")
    print("Same author wrote generator and detectors.")
    print()
    print(f"{'rule':<12}{'tp':>6}{'fp':>6}{'fn':>6}{'precision':>11}{'recall':>8}")
    for rule, c in evaluate_rules(seeds).items():
        flagged, labelled = c["tp"] + c["fp"], c["tp"] + c["fn"]
        precision = c["tp"] / flagged if flagged else 0.0
        recall = c["tp"] / labelled if labelled else 0.0
        print(f"{rule:<12}{c['tp']:>6}{c['fp']:>6}{c['fn']:>6}{precision:>11.3f}{recall:>8.3f}")

    print()
    print("Benford, by share of amounts fabricated. The tool flags only when both tests agree:")
    print(f"{'fabricated':<12}{'p<0.01':>8}{'both':>8}{'mean MAD':>11}{'median p':>11}")
    fractions = [0.0, 0.1, 0.2, 0.4]
    for fraction, chi2_only, flags, mad, p in evaluate_benford(seeds, fractions):
        chi2_cell = f"{chi2_only}/{args.seeds}"
        both_cell = f"{flags}/{args.seeds}"
        print(f"{fraction:<12.0%}{chi2_cell:>8}{both_cell:>8}{mad:>11.4f}{p:>11.4f}")


if __name__ == "__main__":
    main()
