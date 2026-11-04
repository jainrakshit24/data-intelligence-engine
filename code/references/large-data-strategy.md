# Large-data strategy

Load this for DATA_PROFILE, and whenever a file is large, a glob, an Excel workbook, or anything other than a local file.

## Contents
- How the scripts read data
- Size bands and what changes
- Sampling
- Excel
- Databases and remote sources
- What to put in the COVERAGE line

## How the scripts read data

All scripts use DuckDB. DuckDB **streams** the file: it never needs the whole file in memory.
- DuckDB's working memory is capped at **1 GB** by default (`DIE_MEMORY_LIMIT=4GB` raises it). Work that needs more spills to a private temp directory, which is deleted on exit. The cap is on DuckDB's buffers, **not the whole process**: measured peaks were 1.35 GB (profile, 10M rows) and 1.63 GB (reconcile, 10M × 10M rows). Budget about 2 GB of RAM.
- The scripts never write into the user's working directory.
- Measured on an 8-core machine: 10M rows (734 MB CSV) profiles in ~56 s at ≤1.35 GB RSS; the summary takes ~1 s.

So the default strategy is **whole file, streamed**. Choose something else only for a reason, and say which reason.

## Size bands and what changes

| File | Default | What changes |
|---|---|---|
| < 1 GiB | Whole, exact | Nothing — every count is exact |
| ≥ 1 GiB | Whole, streamed | Distinct counts and quantiles for **non-key** columns become approximate (`≈`). Key candidates stay exact, because uniqueness claims need exact counts |
| Very large, or a quick look is enough | `dataset_summary.py` first (one cheap scan), then decide | — |
| User wants an answer in seconds | `--sample-rows N` | Everything becomes an ESTIMATE (below) |

## Sampling

`--sample-rows N` takes a reservoir sample of N rows with a fixed seed (repeatable).
- Every number from a sample is an **estimate**. Say "≈ 2.4% (sample of 200,000 of 10,000,000 rows)".
- A sample **cannot** prove absence. "No duplicates in the sample" is not "no duplicates". Duplicate and key checks must run on the whole file (`detect_duplicates.py` never samples).
- A sample cannot give a superlative ("the largest customer"). Rule 6.
- Rare events (< 1/N) are likely to be missed entirely. Say so when they matter.

## Excel

- `.xlsx` needs DuckDB's `excel` extension, which is **downloaded** on first use. The scripts refuse (exit 4) until `--allow-extension-download` is passed. Ask the user before passing it, and say that it downloads code from the DuckDB extension repository.
- Without the extension the scripts still list the **sheet names and declared row counts**, read straight from the file.
- **A sheet declaring 1,048,576 rows was probably truncated** when it was exported to Excel. The scripts flag this. Ask for the source data.
- Only one sheet is read per run (`--sheet NAME`). The COVERAGE line must say "sheets: 1 of N".
- `.xls` (old binary format) is not supported. Ask for `.xlsx` or CSV.

## Databases and remote sources

Not scripted in Phase 1. If the data is in a database:
1. Prefer that the user exports a table or query result to Parquet/CSV, then profile that file.
2. Or give them aggregate-only SQL to run (counts, null counts, `count(DISTINCT)`, min/max on non-identifier columns) and ask for the result.
3. Never ask for raw rows to be pasted, and never claim a database result you did not see (rule 2).

## What to put in the COVERAGE line

Copy the scripts' COVERAGE line, then add anything you did on top:

```
COVERAGE: 200,000/10,000,000 rows · 1/1 files · strategy: sample (reservoir, seed 42) — ESTIMATES · filters: none
```

If you combined several runs, coverage is the **smallest** of them, not the largest.
