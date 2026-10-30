from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from ledger_forensics.detectors import (
    Config,
    find_duplicates,
    find_just_below,
    find_round_vendors,
    find_splits,
    find_weekend,
    is_round,
    normalize_invoice,
    normalize_vendor,
)
from ledger_forensics.ledger import Entry

MONDAY = date(2030, 1, 7)
CONFIG = Config(approval_threshold=D("10000"))


def entry(entry_id, amount, day=0, vendor="Example A", invoice=None, approver="x"):
    return Entry(
        entry_id,
        MONDAY + timedelta(days=day),
        vendor,
        invoice if invoice is not None else f"INV-{entry_id}",
        D(str(amount)),
        approver,
    )


def ids(findings):
    return [set(f.entry_ids) for f in findings]


@pytest.mark.parametrize(
    "spelling", ["INV-00123", "inv 123", "INV123", "inv/0123", " Inv-000123 "]
)
def test_invoice_normalisation(spelling):
    assert normalize_invoice(spelling) == "INV123"


def test_vendor_normalisation():
    assert normalize_vendor("Example Supply Ltd.") == normalize_vendor("EXAMPLE SUPPLY")
    assert normalize_vendor("Example Supply") != normalize_vendor("Example Supplies")


def test_exact_duplicate_found_months_apart():
    rows = [entry("a", 500, invoice="INV-1"), entry("b", 500, day=90, invoice="inv 001")]
    findings = find_duplicates(rows, CONFIG)
    assert ids(findings) == [{"a", "b"}]
    assert findings[0].severity == "high"


def test_near_duplicate_needs_the_window():
    near = [entry("a", 500), entry("b", 500, day=3)]
    far = [entry("a", 500), entry("b", 500, day=30)]
    findings = find_duplicates(near, CONFIG)
    assert ids(findings) == [{"a", "b"}]
    assert findings[0].severity == "medium"
    assert find_duplicates(far, CONFIG) == []


def test_recurring_fixed_fee_is_not_a_duplicate():
    rows = [entry(str(i), 800, day=30 * i) for i in range(12)]
    assert find_duplicates(rows, CONFIG) == []


def test_different_vendor_or_amount_is_not_a_duplicate():
    rows = [entry("a", 500), entry("b", 500, vendor="Example B"), entry("c", 501)]
    assert find_duplicates(rows, CONFIG) == []


def test_small_amounts_ignored():
    assert find_duplicates([entry("a", 20), entry("b", 20, day=1)], CONFIG) == []


def test_negative_amounts_ignored():
    assert find_duplicates([entry("a", -500), entry("b", -500, day=1)], CONFIG) == []


def test_split_found_and_detail_is_specific():
    rows = [entry("a", 6000), entry("b", 5000, day=2)]
    findings = find_splits(rows, CONFIG)
    assert ids(findings) == [{"a", "b"}]
    assert "2 invoices below 10000 totalling 11000" in findings[0].detail


def test_split_requires_same_vendor_and_approver():
    assert find_splits([entry("a", 6000), entry("b", 5000, vendor="Example B")], CONFIG) == []
    assert find_splits([entry("a", 6000), entry("b", 5000, approver="y")], CONFIG) == []


def test_split_requires_window_and_sum():
    assert find_splits([entry("a", 6000), entry("b", 5000, day=30)], CONFIG) == []
    assert find_splits([entry("a", 4000), entry("b", 5000, day=1)], CONFIG) == []


def test_invoice_above_threshold_is_not_a_split_part():
    assert find_splits([entry("a", 15000), entry("b", 5000)], CONFIG) == []


def test_duplicate_payment_is_not_also_a_split():
    rows = [entry("a", 6000, invoice="INV-7"), entry("b", 6000, day=1, invoice="INV-7")]
    assert find_splits(rows, CONFIG) == []


def test_overlapping_windows_merge_into_one_cluster():
    rows = [entry("a", 6000), entry("b", 5000, day=3), entry("c", 7000, day=6)]
    findings = find_splits(rows, CONFIG)
    assert ids(findings) == [{"a", "b", "c"}]


def test_small_spend_does_not_add_up_to_a_split():
    rows = [entry(str(i), 400, day=i % 3) for i in range(40)]
    assert find_splits(rows, CONFIG) == []


def test_no_threshold_disables_threshold_rules():
    rows = [entry("a", 9900)]
    assert find_splits(rows, Config()) == []
    assert find_just_below(rows, Config()) == []


@pytest.mark.parametrize(
    ("amount", "flagged"),
    [(9700, True), (9999.99, True), (9699.99, False), (10000, False), (15000, False)],
)
def test_just_below_band_edges(amount, flagged):
    assert bool(find_just_below([entry("a", amount)], CONFIG)) is flagged


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("1000", True), ("5000.00", True), ("1500", False), ("999", False), ("0", False),
     ("-2000", False)],
)
def test_is_round(amount, expected):
    assert is_round(D(amount), D("1000")) is expected


def test_round_vendor_flagged_only_with_rate_count_and_variety():
    shell = [entry(str(i), (i % 5 + 1) * 1000, vendor="Example S") for i in range(8)]
    found = find_round_vendors(shell, CONFIG)
    assert len(found) == 1
    assert len(found[0].entry_ids) == 8

    rent = [entry(str(i), 8000, vendor="Example R") for i in range(12)]
    assert find_round_vendors(rent, CONFIG) == []

    too_few = [entry(str(i), (i + 1) * 1000, vendor="Example F") for i in range(4)]
    assert find_round_vendors(too_few, CONFIG) == []

    diluted = shell + [entry(f"n{i}", 123.45, vendor="Example S") for i in range(100)]
    assert find_round_vendors(diluted, CONFIG) == []


def test_weekend_days_configurable():
    saturday = entry("sat", 10, day=5)
    friday = entry("fri", 10, day=4)
    assert ids(find_weekend([saturday, friday], CONFIG)) == [{"sat"}]
    gulf = Config(weekend_days=frozenset({4, 5}))
    assert ids(find_weekend([saturday, friday], gulf)) == [{"sat"}, {"fri"}]
