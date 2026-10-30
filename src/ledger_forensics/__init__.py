"""Deterministic forensic checks on a payments CSV."""

from .audit import Report, format_report, run_audit
from .benford import BenfordResult, benford_test
from .detectors import Config, Finding
from .ledger import Entry, LoadResult, load_csv

__all__ = [
    "BenfordResult",
    "Config",
    "Entry",
    "Finding",
    "LoadResult",
    "Report",
    "benford_test",
    "format_report",
    "load_csv",
    "run_audit",
]
__version__ = "0.1.0"
