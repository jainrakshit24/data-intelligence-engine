# Data drift and schema change between snapshots

Load this for DATA_DRIFT and SCHEMA_ANALYSIS. It compares two versions of a dataset: last month vs this month, the training extract vs today's, the old feed vs the new one. Change over time inside one dataset is `anomaly-detection.md`. Planning a schema change is `schema-evolution.md`.

## Contents
- Drift, anomaly, reconciliation: which tool
- Running the check
- Schema changes
- Distribution drift
- Reading severity
- What drift does not tell you

## Drift, anomaly, reconciliation: which tool

| Question | Tool |
|---|---|
| "Is this month's data shaped like last month's?" | `drift_check.py` |
| "When did it change, and in which segment?" | `anomaly_detection.py` on the combined history |
| "Did the pipeline lose or duplicate rows between input and output?" | `reconcile.py` (same entities, row by row) |
| "Does the data still honour its contract?" | `quality_checks.py --rules contract.json` |

Drift compares **populations**; reconcile compares **the same keys**. Two snapshots with no shared keys can still be drift-checked.

## Running the check

```bash
python3 scripts/drift_check.py baseline.csv current.csv [--columns a,b] [--fail-on moderate|major]
```

Both files are profiled first (types, missingness, which columns are personal). Only aggregates are printed. Identifier, personal and free-text columns are compared by missing share and distinct ratio only; their values are never compared or printed. Quasi-identifiers (age, gender, postcode) are compared, and a category seen fewer than 5 times is counted but never named.

## Schema changes

| Change | Class | Why |
|---|---|---|
| Column removed | BREAKING | Every consumer that selects it fails or silently gets NULL |
| Type family changed (number → text, date → text) | BREAKING | Casts fail; sorting and aggregation change meaning |
| Column added | additive | Safe for consumers that select columns by name; breaks `SELECT *` into a fixed-width target |
| Removed + added, same type, same missing share and distinct ratio | possible rename | Verify with the producer; a rename is a removal for every consumer |

The type family comes from the profile (a text column that is 98% numbers is "number"). A column that slides from 100% numeric to "mostly numeric" stays in the number family. Its missing share and `quality_checks.py` validity show the bad values.

## Distribution drift

**Numbers.** PSI over the baseline's deciles: each value is placed in the baseline's 10 bins, and

```
PSI = Σ (current share − baseline share) × ln(current share ÷ baseline share)
```

An empty bin is given a share of 0.0001 so the log stays finite. Mean, median and p95 are shown beside it. A median that moved by about ×10ᵏ is labelled a possible unit change.

PSI over deciles is blind to a small slice of extreme values: a 4% slice at ×100 sits inside the top bin, and PSI stays "stable". So the mean is tested too. A mean that moved ≥ 3 standard errors and ≥ 10% (≥ 50%: major) while the deciles held is reported as **a change in the tail**. Find when it happened with `anomaly_detection.py --metric`.

**Categories** (≤ 50 values in the baseline). PSI over the baseline's categories plus one bucket for values the baseline never had. The output names values that vanished, values that are new and their share, and the biggest movers.

**Missingness.** Missing share (null, blank, placeholder) on each side with a two-proportion z-test.

## Reading severity

| PSI | Severity | Typical meaning |
|---|---|---|
| < 0.10 | stable | Sampling noise |
| 0.10 – 0.25 | moderate | A real but modest shift: check whether it is expected (season, campaign, new market) |
| ≥ 0.25 | major | The population or the measurement changed |

These cut-offs are an industry convention from credit scoring, not a statistical test. With under 100 values on either side PSI is marked low-sample: report the counts instead.

Missing share: z ≥ 3 with a change of 1–10 points is moderate, 10+ points major.

`--fail-on moderate|major` exits 1 at that level, and **any breaking schema change** always trips it.

## What drift does not tell you

- **Why.** A major PSI on `amount` says the distribution moved. A ×100 median says "possible unit change". Neither says which system changed it. Go to `root-cause-investigation.md` → `root-cause/field-drift.md`.
- **Whether it matters.** A drifted column nobody uses is noise; a slightly drifted model feature may matter a lot. Ask what consumes the column.
- **Row-level errors.** Two datasets can have identical distributions and every row wrong (shuffled keys). Reconcile on the key for that.
- **Relationships.** Each column is compared alone. A shift in how two columns relate (the price for a given product) needs a grouped comparison: run drift per segment, or EDA (`eda.md`).
