# Python data processing

Load this for TRANSFORMATION when the work is in Python (scripts, jobs, notebooks turned into pipelines).

## Contents
- Choosing the engine
- Structure
- Types and parsing
- Memory and size
- Writing outputs safely
- Testing

## Choosing the engine

| Engine | Use when |
|---|---|
| DuckDB | SQL-shaped work on files of any size on one machine; larger-than-memory; Parquet/CSV/JSON. Same engine as this skill's scripts |
| Polars | DataFrame API, lazy and fast, larger-than-memory with streaming |
| pandas | Small data (fits comfortably in memory), or an existing pandas codebase / library that needs it |
| PySpark | Beyond one machine, or a Spark platform already exists (`pyspark.md`) |

Don't mix engines without a reason; each conversion copies data.

## Structure

- Pure transformation functions (`input -> output`), separate from I/O. They are what you test.
- Configuration (paths, dates, thresholds) as parameters, not constants buried in code.
- One entry point that runs: read → validate → transform → validate → write → log run accounting.
- Log counts at each step (rows in, rows out, rejected with reason). Those numbers fill `templates/pipeline-run-accounting.md`.

## Types and parsing

- Read text columns as text first when the source is dirty (as the profiler does), then parse with explicit formats. Never let a reader guess dates on mixed data.
- Parse money with explicit rules (symbols, separators, decimal comma) and count failures.
- Keep codes with leading zeros as strings (PINs, ZIPs, store codes).
- After parsing, assert: the number of values that became NULL equals the number expected (placeholders), not more.

## Memory and size

- Don't load whole files with pandas past a few GB. Stream with DuckDB/Polars lazy scans, or process in chunks with an explicit aggregation strategy.
- Prefer Parquet for intermediates: typed, compressed, column-pruned reads.
- Measure peak memory on a realistic input before declaring a job safe (`/usr/bin/time -v` reports max RSS).

## Writing outputs safely

- Write to a temporary path, then rename atomically (`os.replace`) — readers never see half a file.
- Never overwrite the input. Never write into a directory you are also reading from in the same run.
- Idempotent outputs: deterministic file names per interval (`orders/date=2026-11-01/part-0.parquet`), overwritten on rerun.
- Record a checksum and row count of each output.

## Testing

- Unit tests on small hand-made inputs that contain the edge cases the profile found (nulls, duplicates, placeholders, mixed formats, leading zeros).
- One end-to-end test on a fixture with planted defects, asserting exact counts — the pattern used by this skill's own `tests/`.
- Reconcile a refactored job's output against the old output (`reconcile.py old.parquet new.parquet --key id --compare all`) before switching.
