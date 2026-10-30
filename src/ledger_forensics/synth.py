"""Seeded synthetic ledger with labelled anomalies, including legitimate look-alikes.

Everything is invented: vendors are named "Example Vendor NNN" and dates are in 2030. The
author of this generator also wrote the detectors, so it tests the code, not the world.

Hard negatives (unlabelled on purpose):
  - a monthly fixed rent and a weekly fixed fee, the same amount repeatedly
  - repeat orders: same vendor and amount, different invoice, a few days apart
  - project batches: several real invoices to a vendor that sum above the threshold
  - retainers: a vendor billing assorted round amounts
  - ordinary weekend postings and amounts that happen to land just below the threshold
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .ledger import Entry

START = date(2030, 1, 1)
DAYS = 365


@dataclass
class Row:
    entry_id: str
    date: date
    vendor: str
    invoice: str
    amount: Decimal
    approver: str
    labels: set[str] = field(default_factory=set)

    def to_entry(self) -> Entry:
        return Entry(self.entry_id, self.date, self.vendor, self.invoice, self.amount,
                     self.approver)


@dataclass(frozen=True)
class SynthConfig:
    n_base: int = 2000
    threshold: Decimal = Decimal("10000")
    n_vendors: int = 120
    duplicates: int = 30
    splits: int = 12
    just_below: int = 15
    round_vendors: int = 2
    weekend_fraud: int = 30
    fabricate_fraction: float = 0.0


def _weekday(rng: random.Random) -> date:
    while True:
        day = START + timedelta(days=rng.randrange(DAYS))
        if day.weekday() < 5:
            return day


def _money(value: float) -> Decimal:
    return Decimal(f"{max(value, 1.0):.2f}")


class _Builder:
    def __init__(self, config: SynthConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng
        self.rows: list[Row] = []
        self.counter = 0
        self.vendors = [f"Example Vendor {i:03d}" for i in range(config.n_vendors)]
        self.approvers = [f"approver-{i:02d}" for i in range(8)]

    def add(self, day: date, vendor: str, amount: Decimal, *, invoice: str | None = None,
            approver: str | None = None, labels: set[str] | None = None) -> Row:
        self.counter += 1
        row = Row(
            entry_id=f"E{self.counter:06d}",
            date=day,
            vendor=vendor,
            invoice=invoice or f"INV-{self.rng.randrange(10**7):07d}",
            amount=amount,
            approver=approver or self.rng.choice(self.approvers),
            labels=labels or set(),
        )
        self.rows.append(row)
        return row

    def base_amount(self) -> Decimal:
        # A wide lognormal has first digits close to Benford's distribution.
        value = math.exp(self.rng.gauss(6.5, 1.7))
        if self.rng.random() < 0.02:  # ordinary rounded figures
            return _money(round(value, -2))
        return _money(value)

    def fabricated_amount(self) -> Decimal:
        # What invented figures tend to look like: mid-range digits, roughly uniform.
        digit = self.rng.randint(1, 9)
        magnitude = self.rng.choice([100, 1000, 1000, 10000])
        return _money((digit + self.rng.random()) * magnitude)

    def base(self) -> None:
        for _ in range(self.config.n_base):
            if self.rng.random() < self.config.fabricate_fraction:
                amount = self.fabricated_amount()
            else:
                amount = self.base_amount()
            if self.rng.random() < 0.02:  # ordinary weekend posting
                day = _weekday(self.rng)
                day += timedelta(days=(5 - day.weekday()) + self.rng.randint(0, 1))
            else:
                day = _weekday(self.rng)
            self.add(day, self.rng.choice(self.vendors), amount)

    def hard_negatives(self) -> None:
        rng = self.rng
        for month in range(12):
            self.add(date(2030, month + 1, 1), "Example Landlord", Decimal("8000.00"))
        for week in range(52):
            self.add(START + timedelta(days=7 * week), "Example Cleaning", Decimal("450.00"))
        for _ in range(15):  # repeat orders
            vendor, amount = rng.choice(self.vendors), _money(rng.uniform(200, 3000))
            first = _weekday(rng)
            self.add(first, vendor, amount)
            self.add(first + timedelta(days=rng.randint(1, 4)), vendor, amount)
        for _ in range(6):  # project batches under one approver
            vendor, approver = rng.choice(self.vendors), rng.choice(self.approvers)
            first = _weekday(rng)
            for offset in range(rng.randint(2, 3)):
                amount = _money(rng.uniform(4000, 9000))
                self.add(first + timedelta(days=offset), vendor, amount, approver=approver)
        for _ in range(8):  # retainer vendor: assorted round bills, a legitimate look-alike
            self.add(_weekday(rng), "Example Advisory", Decimal(rng.randint(1, 5) * 1000))

    def inject_duplicates(self) -> None:
        rng = self.rng
        candidates = [r for r in self.rows if r.amount >= 100 and r.vendor.startswith("Example V")]
        for original in rng.sample(candidates, self.config.duplicates):
            original.labels.add("duplicate")
            style = rng.random()
            if style < 0.5:  # identical invoice, weeks later
                day, invoice = original.date + timedelta(days=rng.randint(1, 60)), original.invoice
            elif style < 0.75:  # invoice reformatted to slip past a naive key
                day = original.date + timedelta(days=rng.randint(1, 60))
                invoice = original.invoice.replace("INV-", "inv ").lstrip()
            else:  # invoice altered by a suffix: only the date window can catch this
                day = original.date + timedelta(days=rng.randint(1, 14))
                invoice = original.invoice + "A"
            self.add(day, original.vendor, original.amount, invoice=invoice,
                     approver=original.approver, labels={"duplicate"})

    def inject_splits(self) -> None:
        rng = self.rng
        threshold = float(self.config.threshold)
        for _ in range(self.config.splits):
            vendor, approver = rng.choice(self.vendors), rng.choice(self.approvers)
            parts = rng.randint(2, 4)
            total = rng.uniform(1.1, 0.9 * parts) * threshold
            first = _weekday(rng)
            for _ in range(parts):
                share = total / parts * rng.uniform(0.85, 1.15)
                amount = _money(min(share, threshold * 0.995))
                day = first + timedelta(days=rng.randint(0, 3))
                self.add(day, vendor, amount, approver=approver, labels={"split"})

    def inject_just_below(self) -> None:
        threshold = float(self.config.threshold)
        for _ in range(self.config.just_below):
            amount = _money(self.rng.uniform(0.975, 0.999) * threshold)
            self.add(_weekday(self.rng), self.rng.choice(self.vendors), amount,
                     labels={"just_below"})

    def inject_round_vendors(self) -> None:
        for i in range(self.config.round_vendors):
            vendor = f"Example Shell {i:02d}"
            for _ in range(self.rng.randint(8, 14)):
                amount = Decimal(self.rng.randint(1, 9) * 1000)
                self.add(_weekday(self.rng), vendor, amount, labels={"round"})

    def inject_weekend(self) -> None:
        for _ in range(self.config.weekend_fraud):
            day = _weekday(self.rng)
            day += timedelta(days=(5 - day.weekday()) + self.rng.randint(0, 1))
            self.add(day, self.rng.choice(self.vendors), self.base_amount(), labels={"weekend"})


def generate(seed: int, config: SynthConfig | None = None) -> list[Row]:
    config = config or SynthConfig()
    rng = random.Random(seed)
    builder = _Builder(config, rng)
    builder.base()
    builder.hard_negatives()
    builder.inject_duplicates()
    builder.inject_splits()
    builder.inject_just_below()
    builder.inject_round_vendors()
    builder.inject_weekend()
    return sorted(builder.rows, key=lambda r: (r.date, r.entry_id))


def write_csv(rows: list[Row], path: str | Path, *, include_labels: bool = True) -> None:
    fields = ["entry_id", "date", "vendor", "invoice", "amount", "approver"]
    if include_labels:
        fields.append("anomaly")
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for r in rows:
            row = [r.entry_id, r.date.isoformat(), r.vendor, r.invoice, str(r.amount), r.approver]
            if include_labels:
                row.append(";".join(sorted(r.labels)))
            writer.writerow(row)
