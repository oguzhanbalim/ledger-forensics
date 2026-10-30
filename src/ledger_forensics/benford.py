"""Benford first-digit test: chi-square against log10(1 + 1/d), and mean absolute deviation."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

EXPECTED = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

# Commonly used first-digit MAD bands in the forensic-accounting literature.
_MAD_BANDS = ((0.006, "close"), (0.012, "acceptable"), (0.015, "marginal"))
MIN_RECOMMENDED_N = 300


def first_digit(amount: Decimal) -> int | None:
    """First significant digit of abs(amount), or None for zero."""
    if amount.is_zero():
        return None
    return next(d for d in amount.as_tuple().digits if d != 0)


def chi2_sf_df8(statistic: float) -> float:
    """P(X >= x) for chi-square with 8 degrees of freedom (closed form for even df)."""
    half = statistic / 2
    return math.exp(-half) * sum(half**k / math.factorial(k) for k in range(4))


def mad_conformity(mad: float) -> str:
    for limit, label in _MAD_BANDS:
        if mad <= limit:
            return label
    return "nonconforming"


@dataclass(frozen=True)
class BenfordResult:
    n: int
    counts: dict[int, int]
    observed: dict[int, float]
    chi2: float
    p_value: float
    mad: float
    conformity: str
    small_sample: bool

    def flagged(self, alpha: float = 0.01) -> bool:
        """Both tests must agree. Chi-square alone rejects nearly everything at large n."""
        return self.p_value < alpha and self.conformity == "nonconforming"


def benford_test(amounts: Iterable[Decimal]) -> BenfordResult:
    counts = dict.fromkeys(range(1, 10), 0)
    for amount in amounts:
        digit = first_digit(amount)
        if digit is not None:
            counts[digit] += 1
    n = sum(counts.values())
    if n == 0:
        raise ValueError("no non-zero amounts to test")
    observed = {d: counts[d] / n for d in counts}
    chi2 = sum((counts[d] - n * EXPECTED[d]) ** 2 / (n * EXPECTED[d]) for d in counts)
    mad = sum(abs(observed[d] - EXPECTED[d]) for d in counts) / 9
    return BenfordResult(
        n=n,
        counts=counts,
        observed=observed,
        chi2=chi2,
        p_value=chi2_sf_df8(chi2),
        mad=mad,
        conformity=mad_conformity(mad),
        small_sample=n < MIN_RECOMMENDED_N,
    )
