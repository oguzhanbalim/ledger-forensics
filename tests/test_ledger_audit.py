import json
from decimal import Decimal as D

import pytest

from ledger_forensics import Config, load_csv, run_audit
from ledger_forensics.cli import main
from ledger_forensics.ledger import parse_amount, parse_date
from ledger_forensics.synth import SynthConfig, generate, write_csv


@pytest.mark.parametrize(
    ("raw", "value"),
    [("1234.56", "1234.56"), ("1,234.56", "1234.56"), ("1,234,567", "1234567"), ("-50", "-50"),
     (" 12 ", "12")],
)
def test_parse_amount_default(raw, value):
    assert parse_amount(raw) == D(value)


@pytest.mark.parametrize(
    ("raw", "value"),
    [("1.234,56", "1234.56"), ("1234,56", "1234.56"), ("1.234.567", "1234567")],
)
def test_parse_amount_decimal_comma(raw, value):
    assert parse_amount(raw, decimal_comma=True) == D(value)


@pytest.mark.parametrize("raw", ["", "abc", "1.234,56", "12,34", "1,23.4", "NaN", "Infinity"])
def test_parse_amount_refuses_to_guess(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


def test_parse_date_formats():
    assert parse_date("2030-03-02") == parse_date("02.03.2030") == parse_date("02/03/2030")
    with pytest.raises(ValueError):
        parse_date("March 2")


def test_load_csv_reports_bad_rows(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text(
        "entry_id,date,vendor,invoice,amount\n"
        "1,2030-01-07,A,I1,100.00\n"
        "2,not-a-date,A,I2,100.00\n"
        "3,2030-01-07,A,I3,abc\n"
        "1,2030-01-07,A,I4,100.00\n"
        ",2030-01-07,A,I5,100.00\n",
        encoding="utf-8",
    )
    loaded = load_csv(path)
    assert [e.entry_id for e in loaded.entries] == ["1"]
    assert [r.line for r in loaded.rejected] == [3, 4, 5, 6]


def test_load_csv_missing_columns_and_custom_names(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("No,Tarih,Firma,Fatura,Tutar\n1,07.01.2030,A,I1,\"1.234,50\"\n", "utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_csv(path)
    columns = {"entry_id": "No", "date": "Tarih", "vendor": "Firma", "invoice": "Fatura",
               "amount": "Tutar"}
    loaded = load_csv(path, columns=columns, decimal_comma=True)
    assert loaded.entries[0].amount == D("1234.50")


def test_generator_is_deterministic_and_labelled():
    a, b = generate(5), generate(5)
    assert [(r.entry_id, r.amount, sorted(r.labels)) for r in a] == [
        (r.entry_id, r.amount, sorted(r.labels)) for r in b
    ]
    assert generate(6)[0].amount != a[0].amount or generate(6)[1].amount != a[1].amount
    labels = {label for r in a for label in r.labels}
    assert labels == {"duplicate", "split", "just_below", "round", "weekend"}
    assert all(r.vendor.startswith("Example") for r in a)


def test_audit_is_deterministic_and_finds_each_rule():
    rows = generate(11)
    config = Config(approval_threshold=SynthConfig().threshold)
    one = run_audit([r.to_entry() for r in rows], config)
    two = run_audit([r.to_entry() for r in rows], config)
    assert one.to_dict() == two.to_dict()
    for rule in ("duplicate", "split", "just_below", "round", "weekend"):
        labelled = {r.entry_id for r in rows if rule in r.labels}
        assert len(one.flagged_ids(rule) & labelled) / len(labelled) > 0.7, rule


def test_hard_negatives_really_are_in_the_data():
    # If these stop being flagged, the published precision would be overstated by the generator.
    rows = generate(11)
    config = Config(approval_threshold=SynthConfig().threshold)
    report = run_audit([r.to_entry() for r in rows], config)
    by_id = {r.entry_id: r for r in rows}
    for rule in ("duplicate", "split", "round", "weekend"):
        false_positives = [i for i in report.flagged_ids(rule) if rule not in by_id[i].labels]
        assert false_positives, rule


def test_fabrication_raises_mad():
    clean = SynthConfig(duplicates=0, splits=0, just_below=0, round_vendors=0, weekend_fraud=0)
    dirty = SynthConfig(duplicates=0, splits=0, just_below=0, round_vendors=0, weekend_fraud=0,
                        fabricate_fraction=0.4)
    clean_report = run_audit([r.to_entry() for r in generate(3, clean)])
    dirty_report = run_audit([r.to_entry() for r in generate(3, dirty)])
    assert clean_report.benford.mad < dirty_report.benford.mad


def test_empty_ledger_does_not_crash():
    report = run_audit([])
    assert report.entries == 0 and report.benford is None and report.findings == []


def test_cli_generate_then_audit(tmp_path, capsys):
    path = tmp_path / "ledger.csv"
    assert main(["generate", str(path), "--seed", "2"]) == 0
    assert "synthetic" in capsys.readouterr().out
    assert main(["audit", str(path), "--threshold", "10000"]) == 0
    text = capsys.readouterr().out
    assert "benford:" in text and "split:" in text
    assert "not evidence of wrongdoing" in text

    assert main(["audit", str(path), "--threshold", "10000", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entries"] > 2000
    assert {f["rule"] for f in data["findings"]} >= {"duplicate", "split"}


def test_written_csv_round_trips(tmp_path):
    rows = generate(4)
    path = tmp_path / "x.csv"
    write_csv(rows, path)
    loaded = load_csv(path)
    assert loaded.rejected == []
    assert sum(e.amount for e in loaded.entries) == sum(r.amount for r in rows)
