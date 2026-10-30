"""Rule detectors. Each returns Findings naming the entries involved; none of them proves fraud."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from .ledger import Entry

DUPLICATE = "duplicate"
SPLIT = "split"
JUST_BELOW = "just_below"
ROUND = "round"
WEEKEND = "weekend"


@dataclass(frozen=True)
class Finding:
    rule: str
    entry_ids: tuple[str, ...]
    detail: str
    severity: str = "review"


@dataclass(frozen=True)
class Config:
    approval_threshold: Decimal | None = None
    duplicate_window_days: int = 5
    duplicate_min_amount: Decimal = Decimal("100")
    split_window_days: int = 5
    split_min_part_ratio: Decimal = Decimal("0.1")
    just_below_band: Decimal = Decimal("0.03")
    round_unit: Decimal = Decimal("1000")
    round_min_rate: float = 0.3
    round_min_count: int = 5
    round_min_distinct: int = 3
    weekend_days: frozenset[int] = field(default_factory=lambda: frozenset({5, 6}))


_LEGAL_SUFFIX = re.compile(r"\b(?:LTD|LIMITED|LLC|INC|GMBH|AS|STI)\b")
_NON_ALNUM = re.compile(r"[^0-9A-Z]")
_LEADING_ZEROS = re.compile(r"(?<![0-9])0+(?=[0-9])")


def normalize_vendor(name: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", name.upper())
    return " ".join(_LEGAL_SUFFIX.sub(" ", cleaned).split())


def normalize_invoice(invoice: str) -> str:
    """INV-00123, inv 123 and INV123 all reduce to INV123."""
    return _NON_ALNUM.sub("", _LEADING_ZEROS.sub("", invoice.upper()))


def find_duplicates(entries: list[Entry], config: Config) -> list[Finding]:
    """Same vendor and amount, with the same invoice (any date) or within a short window."""
    groups: dict[tuple[str, Decimal], list[Entry]] = defaultdict(list)
    for entry in entries:
        if entry.amount >= config.duplicate_min_amount:
            groups[(normalize_vendor(entry.vendor), entry.amount)].append(entry)

    findings = []
    for (vendor, amount), group in groups.items():
        if len(group) < 2:
            continue
        same_invoice: dict[str, list[Entry]] = defaultdict(list)
        for entry in group:
            key = normalize_invoice(entry.invoice)
            if key:
                same_invoice[key].append(entry)
        exact_ids: set[str] = set()
        for invoice, members in same_invoice.items():
            if len(members) > 1:
                ids = tuple(e.entry_id for e in members)
                exact_ids.update(ids)
                findings.append(
                    Finding(DUPLICATE, ids, f"{vendor} {amount} invoice {invoice} repeated", "high")
                )

        window = timedelta(days=config.duplicate_window_days)
        ordered = sorted((e for e in group if e.entry_id not in exact_ids), key=lambda e: e.date)
        cluster: list[Entry] = []
        for entry in ordered:
            if cluster and entry.date - cluster[-1].date > window:
                findings.extend(_near_finding(cluster, vendor, amount, config))
                cluster = []
            cluster.append(entry)
        findings.extend(_near_finding(cluster, vendor, amount, config))
    return findings


def _near_finding(
    cluster: list[Entry], vendor: str, amount: Decimal, config: Config
) -> list[Finding]:
    if len(cluster) < 2:
        return []
    detail = (
        f"{vendor} {amount} paid {len(cluster)} times within "
        f"{config.duplicate_window_days} days, different invoices"
    )
    return [Finding(DUPLICATE, tuple(e.entry_id for e in cluster), detail, "medium")]


def find_splits(entries: list[Entry], config: Config) -> list[Finding]:
    """Invoices each below the threshold, same vendor and approver, summing above it within days.

    Repeated invoice numbers count once, so a duplicate payment is not also read as a split.
    Parts below split_min_part_ratio of the threshold are ignored as ordinary small spend.
    """
    threshold = config.approval_threshold
    if threshold is None:
        return []
    minimum = threshold * config.split_min_part_ratio
    groups: dict[tuple[str, str], dict[str, Entry]] = defaultdict(dict)
    for entry in entries:
        if minimum <= entry.amount < threshold:
            key = (normalize_vendor(entry.vendor), entry.approver)
            invoice = normalize_invoice(entry.invoice) or entry.entry_id
            groups[key].setdefault(invoice, entry)

    findings = []
    window = timedelta(days=config.split_window_days)
    for (vendor, approver), by_invoice in groups.items():
        ordered = sorted(by_invoice.values(), key=lambda e: (e.date, e.entry_id))
        clusters: list[list[Entry]] = []
        left = 0
        total = Decimal(0)
        for right, entry in enumerate(ordered):
            total += entry.amount
            while entry.date - ordered[left].date > window:
                total -= ordered[left].amount
                left += 1
            if total >= threshold and right > left:
                members = ordered[left : right + 1]
                if clusters and members[0].date <= clusters[-1][-1].date:
                    known = {e.entry_id for e in clusters[-1]}
                    clusters[-1].extend(e for e in members if e.entry_id not in known)
                else:
                    clusters.append(list(members))
        for cluster in clusters:
            amount = sum(e.amount for e in cluster)
            who = f", approver {approver}" if approver else ""
            detail = (
                f"{vendor}{who}: {len(cluster)} invoices below {threshold} "
                f"totalling {amount} from {cluster[0].date} to {cluster[-1].date}"
            )
            findings.append(Finding(SPLIT, tuple(e.entry_id for e in cluster), detail))
    return findings


def find_just_below(entries: list[Entry], config: Config) -> list[Finding]:
    threshold = config.approval_threshold
    if threshold is None:
        return []
    floor = threshold * (1 - config.just_below_band)
    return [
        Finding(JUST_BELOW, (e.entry_id,), f"{e.amount} is within band below {threshold}")
        for e in entries
        if floor <= e.amount < threshold
    ]


def is_round(amount: Decimal, unit: Decimal) -> bool:
    return amount >= unit and amount % unit == 0


def round_rate(entries: list[Entry], config: Config) -> float:
    positive = [e for e in entries if e.amount > 0]
    if not positive:
        return 0.0
    return sum(is_round(e.amount, config.round_unit) for e in positive) / len(positive)


def find_round_vendors(entries: list[Entry], config: Config) -> list[Finding]:
    """Vendors with a high rate of round amounts. A single fixed fee (rent) does not count."""
    by_vendor: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        if entry.amount > 0:
            by_vendor[normalize_vendor(entry.vendor)].append(entry)
    findings = []
    for vendor, group in by_vendor.items():
        rounds = [e for e in group if is_round(e.amount, config.round_unit)]
        rate = len(rounds) / len(group)
        if (
            len(rounds) >= config.round_min_count
            and rate >= config.round_min_rate
            and len({e.amount for e in rounds}) >= config.round_min_distinct
        ):
            detail = f"{vendor}: {len(rounds)}/{len(group)} payments are multiples of "
            detail += f"{config.round_unit} ({rate:.0%})"
            findings.append(Finding(ROUND, tuple(e.entry_id for e in rounds), detail))
    return findings


def find_weekend(entries: list[Entry], config: Config) -> list[Finding]:
    return [
        Finding(WEEKEND, (e.entry_id,), f"posted on {e.date:%A} {e.date}")
        for e in entries
        if e.date.weekday() in config.weekend_days
    ]
