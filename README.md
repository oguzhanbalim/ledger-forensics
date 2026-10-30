# ledger-forensics

The checks a forensic accountant runs first, as a small library with no model in the loop: same CSV in, same findings out, every flag traceable to a rule you can read.

Payment anomalies have a handful of classic signatures that are cheap to test for and easy to explain to an auditor. This does those and nothing else, with the standard library only, and it reports its own false-positive rate rather than a confident verdict.

## Quickstart

```
pip install -e .
ledger-forensics generate ledger.csv --seed 1
ledger-forensics audit ledger.csv --threshold 10000 --max-per-rule 2
```

The generator writes invented data: vendors are "Example Vendor NNN" and dates are in 2030.

```
wrote 2245 rows to ledger.csv (seed 1), synthetic
entries: 2245   total: 6059076.39
benford: chi2=10.73 p=0.2172 MAD=0.0062 (acceptable) -> no flag
round-amount rate: 1.6%
weekend-posting rate: 4.1%
duplicate: 38 finding(s)
  [medium] EXAMPLE VENDOR 006 2301.31 paid 2 times within 5 days, different invoices  ['E002073', 'E002074']
  [medium] EXAMPLE VENDOR 074 299.71 paid 2 times within 5 days, different invoices  ['E002089', 'E002090']
  ... 36 more
split: 21 finding(s)
  [review] EXAMPLE VENDOR 056, approver approver-04: 4 invoices below 10000 totalling 18749.32 from 2030-02-13 to 2030-02-15  ['E002174', 'E002176', 'E002175', 'E002177']
  [review] EXAMPLE VENDOR 101, approver approver-03: 2 invoices below 10000 totalling 12489.76 from 2030-03-27 to 2030-03-28  ['E002095', 'E002096']
  ... 19 more
just_below: 18 finding(s)
  [review] 9943.22 is within band below 10000  ['E002197']
  [review] 9921.99 is within band below 10000  ['E002194']
  ... 16 more
round: 3 finding(s)
  [review] EXAMPLE SHELL 00: 9/9 payments are multiples of 1000 (100%)  ['E002200', 'E002204', 'E002205', 'E002207', 'E002202', 'E002199', 'E002201', 'E002206', 'E002203']
  [review] EXAMPLE SHELL 01: 8/8 payments are multiples of 1000 (100%)  ['E002210', 'E002208', 'E002209', 'E002211', 'E002213', 'E002215', 'E002214', 'E002212']
  ... 1 more
weekend: 92 finding(s)
  [review] posted on Saturday 2030-01-19  ['E000208']
  [review] posted on Saturday 2030-01-19  ['E001106']
  ... 90 more
Findings are prompts for review, not evidence of wrongdoing.
```

Your CSV needs `entry_id, date, vendor, invoice, amount`, with `approver` optional. `load_csv(path, columns={"amount": "Tutar"}, decimal_comma=True)` handles other headers and `1.234,56` amounts. Rows that don't parse are reported, not dropped. An amount that fits neither format is rejected, because the tool won't guess.

## What it checks

| Rule | Fires when |
|---|---|
| Benford first digit | Chi-square p < 0.01 **and** MAD above 0.015. Reports both. |
| `duplicate` | Same vendor and amount, plus same normalised invoice (`INV-00123` = `inv 123`) at any date, or any invoice within 5 days |
| `split` | Invoices under the threshold, same vendor and approver, within 5 days, summing to at least the threshold. Parts under 10% of the threshold are ignored. |
| `just_below` | Amount within 3% below the threshold |
| `round` | A vendor with at least 30% of payments as multiples of 1000, at least 5 of them, at least 3 distinct values (one fixed rent doesn't count) |
| `weekend` | Posted on a weekend day. `--weekend 4,5` for a Friday-Saturday week. |

All of these are in `Config`.

## How well does it work?

Only on synthetic data so far. `python scripts/evaluate.py`:

```
Synthetic ledgers, seeds 1-20, about 2250 rows each. Entry-level counts.
Same author wrote generator and detectors.

rule            tp    fp    fn  precision  recall
duplicate     1012   605   188      0.626   0.843
split          714   386     0      0.649   1.000
just_below     300    88     0      0.773   1.000
round          436   152     0      0.741   1.000
weekend        600  1399     0      0.300   1.000

Benford, by share of amounts fabricated. The tool flags only when both tests agree:
fabricated    p<0.01    both   mean MAD   median p
0%             10/20    0/20     0.0077     0.0233
10%            19/20    0/20     0.0112     0.0002
20%            20/20   15/20     0.0164     0.0000
40%            20/20   20/20     0.0268     0.0000
```

**I wrote the generator and the detectors, so don't read these as real-world performance.** The generator encodes my assumptions about what fraud looks like, and the detectors encode the same assumptions. Specifically:

- **Recall of 1.000 is by construction** for `split`, `just_below`, `round` and `weekend`. The injected anomalies fall inside the rule parameters because I chose both. A split spread over two weeks or across two approvers would be missed, and the generator doesn't produce one.
- **`duplicate` recall of 0.843 is a real miss:** an invoice number altered with a suffix and paid more than 5 days later gets through.
- **The precision figures depend on hard negatives I decided to add:** repeat orders, project batches, a retainer vendor and ordinary weekend postings. Change their count and precision moves. The comparison between rules means more than the absolute values. On real data, expect a base rate of true anomalies far lower than the roughly 5% of rows here, and so much lower precision.
- **`weekend` at 0.300** is what a rule with no other context gets: it lists every weekend posting and leaves the judgement to you.

The Benford table has two lessons. Chi-square alone fired on 10 of 20 ledgers with no fabricated amounts, which is why the tool also requires MAD to agree (the "clean" ledgers aren't perfectly Benford; they include fixed fees and a lognormal approximation). The cost of requiring both shows in the 10% row: with 10% of amounts fabricated it flagged 0 of 20. The fabricated-amount model is also mine, and real fabrication may look different.

The Benford arithmetic has one independent check: the first digits of 2^0 to 2^999 match their known counts, and the chi-square survival function matches published critical values.

## Limits

- **A finding is a prompt for review, not evidence of wrongdoing.** Nothing here has been tested on a real ledger or reviewed by an auditor.
- **Benford needs the right population.** It suits amounts spanning several orders of magnitude and at least a few hundred records. It doesn't suit data with assigned or capped amounts, and a pass proves nothing. The output warns under 300 records.
- **One approval threshold.** Multiple tiers aren't supported.
- **Vendor matching is exact after normalisation.** `Example Supply` and `Example Suply` are two vendors, and related vendors aren't linked.
- `round` uses one unit (1000), which suits some currencies and ledgers only. Set `round_unit` for yours.
- It doesn't convert currencies, and it treats credit notes (negative amounts) as outside the duplicate, split and round rules.
- Single process, in memory, standard library. Fine for a few hundred thousand rows by design; I haven't benchmarked it.
- Tested locally on Python 3.12 only. CI is configured for 3.11 and 3.12 but this repository has not been pushed.

## License

MIT
