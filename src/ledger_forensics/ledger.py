"""Load a payments CSV into typed entries. Rejected rows are reported, never dropped silently."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED = ("entry_id", "date", "vendor", "invoice", "amount")
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y")
_PLAIN_AMOUNT = re.compile(r"[-+]?\d+(?:\.\d+)?")
_GROUPED_AMOUNT = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_GROUPED_COMMA_DECIMAL = re.compile(r"[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_PLAIN_COMMA_DECIMAL = re.compile(r"[-+]?\d+(?:,\d+)?")


@dataclass(frozen=True)
class Entry:
    entry_id: str
    date: date
    vendor: str
    invoice: str
    amount: Decimal
    approver: str = ""


@dataclass(frozen=True)
class Rejected:
    line: int
    reason: str


@dataclass(frozen=True)
class LoadResult:
    entries: list[Entry]
    rejected: list[Rejected]


def parse_amount(raw: str, *, decimal_comma: bool = False) -> Decimal:
    """Parse an amount without guessing: '1,234.56' by default, '1.234,56' with decimal_comma."""
    text = raw.strip().replace(" ", "")
    if decimal_comma:
        if not (_GROUPED_COMMA_DECIMAL.fullmatch(text) or _PLAIN_COMMA_DECIMAL.fullmatch(text)):
            raise ValueError(f"bad amount {raw!r}")
        text = text.replace(".", "").replace(",", ".")
    else:
        if not (_GROUPED_AMOUNT.fullmatch(text) or _PLAIN_AMOUNT.fullmatch(text)):
            raise ValueError(f"bad amount {raw!r}")
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"bad amount {raw!r}") from error


def parse_date(raw: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"bad date {raw!r}")


def load_csv(
    path: str | Path,
    *,
    columns: dict[str, str] | None = None,
    decimal_comma: bool = False,
) -> LoadResult:
    """Read a CSV. `columns` maps our names to yours, e.g. {'amount': 'Tutar'}."""
    names = {name: name for name in (*REQUIRED, "approver")}
    names.update(columns or {})
    entries: list[Entry] = []
    rejected: list[Rejected] = []
    seen_ids: set[str] = set()

    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [names[r] for r in REQUIRED if names[r] not in header]
        if missing:
            raise ValueError(f"missing columns: {', '.join(missing)}")
        for row in reader:
            try:
                entry_id = (row[names["entry_id"]] or "").strip()
                if not entry_id:
                    raise ValueError("empty entry_id")
                if entry_id in seen_ids:
                    raise ValueError(f"repeated entry_id {entry_id!r}")
                entry = Entry(
                    entry_id=entry_id,
                    date=parse_date(row[names["date"]] or ""),
                    vendor=(row[names["vendor"]] or "").strip(),
                    invoice=(row[names["invoice"]] or "").strip(),
                    amount=parse_amount(row[names["amount"]] or "", decimal_comma=decimal_comma),
                    approver=(row.get(names["approver"]) or "").strip(),
                )
            except ValueError as error:
                rejected.append(Rejected(reader.line_num, str(error)))
                continue
            seen_ids.add(entry_id)
            entries.append(entry)
    return LoadResult(entries, rejected)
