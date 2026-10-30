"""Run every check and assemble a report. Same input, same output: no clock, no randomness."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from .benford import BenfordResult, benford_test
from .detectors import (
    Config,
    Finding,
    find_duplicates,
    find_just_below,
    find_round_vendors,
    find_splits,
    find_weekend,
    round_rate,
)
from .ledger import Entry


@dataclass(frozen=True)
class Report:
    entries: int
    total_amount: str
    benford: BenfordResult | None
    round_rate: float
    weekend_rate: float
    findings: list[Finding]

    def flagged_ids(self, rule: str) -> set[str]:
        return {i for f in self.findings if f.rule == rule for i in f.entry_ids}

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.benford is not None:
            data["benford"]["flagged"] = self.benford.flagged()
        return data


def run_audit(entries: list[Entry], config: Config | None = None) -> Report:
    config = config or Config()
    findings = [
        *find_duplicates(entries, config),
        *find_splits(entries, config),
        *find_just_below(entries, config),
        *find_round_vendors(entries, config),
        *find_weekend(entries, config),
    ]
    amounts = [e.amount for e in entries if not e.amount.is_zero()]
    weekend = sum(e.date.weekday() in config.weekend_days for e in entries)
    return Report(
        entries=len(entries),
        total_amount=str(sum((e.amount for e in entries), start=0)),
        benford=benford_test(amounts) if amounts else None,
        round_rate=round_rate(entries, config),
        weekend_rate=weekend / len(entries) if entries else 0.0,
        findings=findings,
    )


def format_report(report: Report, *, max_per_rule: int = 5) -> str:
    lines = [f"entries: {report.entries}   total: {report.total_amount}"]
    if report.benford:
        b = report.benford
        verdict = "FLAG" if b.flagged() else "no flag"
        lines.append(
            f"benford: chi2={b.chi2:.2f} p={b.p_value:.4f} MAD={b.mad:.4f} "
            f"({b.conformity}) -> {verdict}"
        )
        if b.small_sample:
            lines.append(f"  warning: n={b.n} is small for a first-digit test")
    lines.append(f"round-amount rate: {report.round_rate:.1%}")
    lines.append(f"weekend-posting rate: {report.weekend_rate:.1%}")
    counts = Counter(f.rule for f in report.findings)
    for rule in ("duplicate", "split", "just_below", "round", "weekend"):
        lines.append(f"{rule}: {counts[rule]} finding(s)")
        shown = [f for f in report.findings if f.rule == rule][:max_per_rule]
        for finding in shown:
            lines.append(f"  [{finding.severity}] {finding.detail}  {list(finding.entry_ids)}")
        if counts[rule] > len(shown):
            lines.append(f"  ... {counts[rule] - len(shown)} more")
    lines.append("Findings are prompts for review, not evidence of wrongdoing.")
    return "\n".join(lines)
