import math
from decimal import Decimal

import pytest

from ledger_forensics.benford import (
    EXPECTED,
    benford_test,
    chi2_sf_df8,
    first_digit,
    mad_conformity,
)


@pytest.mark.parametrize(
    ("raw", "digit"),
    [("1500", 1), ("0.0456", 4), ("-32.10", 3), ("9", 9), ("1E+3", 1), ("100.00", 1), ("0", None),
     ("0.00", None)],
)
def test_first_digit(raw, digit):
    assert first_digit(Decimal(raw)) == digit


def test_expected_distribution():
    assert math.isclose(EXPECTED[1], 0.30103, abs_tol=1e-5)
    assert math.isclose(EXPECTED[9], 0.04576, abs_tol=1e-5)
    assert math.isclose(sum(EXPECTED.values()), 1.0)


@pytest.mark.parametrize(
    ("statistic", "p"),
    [(15.507, 0.05), (20.090, 0.01), (26.124, 0.001)],
)
def test_chi2_survival_matches_published_critical_values(statistic, p):
    assert math.isclose(chi2_sf_df8(statistic), p, rel_tol=0.01)


def test_chi2_survival_at_zero_is_one():
    assert chi2_sf_df8(0) == 1.0


def test_powers_of_two_match_known_first_digit_counts():
    # An independent anchor: the first digits of 2^0 .. 2^999 are a known result.
    result = benford_test(Decimal(2**n) for n in range(1000))
    assert list(result.counts.values()) == [301, 176, 125, 97, 79, 69, 56, 52, 45]
    assert result.conformity == "close"
    assert not result.flagged()


def test_hand_checked_statistics_on_small_sample():
    amounts = [Decimal(str(d)) for d in range(1, 10)]  # one of each digit
    result = benford_test(amounts)
    expected_chi2 = sum((1 - 9 * EXPECTED[d]) ** 2 / (9 * EXPECTED[d]) for d in range(1, 10))
    expected_mad = sum(abs(1 / 9 - EXPECTED[d]) for d in range(1, 10)) / 9
    assert math.isclose(result.chi2, expected_chi2)
    assert math.isclose(result.mad, expected_mad)
    assert result.small_sample


def test_uniform_digits_are_flagged_at_scale():
    amounts = [Decimal(d) for d in range(1, 10)] * 200
    result = benford_test(amounts)
    assert result.flagged()
    assert result.conformity == "nonconforming"


def test_zero_only_is_rejected():
    with pytest.raises(ValueError):
        benford_test([Decimal(0)])


@pytest.mark.parametrize(
    ("mad", "label"),
    [(0.004, "close"), (0.010, "acceptable"), (0.014, "marginal"), (0.02, "nonconforming")],
)
def test_mad_bands(mad, label):
    assert mad_conformity(mad) == label
