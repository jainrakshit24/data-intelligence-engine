# SQL intelligence

Load this for SQL_ANALYSIS and SQL_OPTIMIZATION, with `safe-database-access.md`. The workflow is `workflows/optimize-sql.md`.

## Contents
- Run the checker first
- Reading a query: grain first
- Rule catalogue
- Optimising: measure, then change one thing
- Translating between dialects
- Writing new SQL

## Run the checker first

```bash
python3 scripts/sql_check.py query.sql --dialect snowflake            # what it reads/writes, risky patterns
python3 scripts/sql_check.py query.sql --lineage revenue              # where a column comes from
python3 scripts/sql_check.py query.sql --to bigquery                  # translate (NOT_VERIFIED until run there)
python3 scripts/sql_check.py query.sql --dialect duckdb --table orders=orders.csv --count   # prove it runs
python3 scripts/sql_check.py fct.sql --dialect duckdb --table … --count --grain order_id      # prove the grain holds
```

- Always pass `--dialect`. Without it, engine-specific syntax may not parse (exit 6) or may parse into a different meaning.
- Findings are **patterns to check, not proven bugs** (an OBSERVATION about the code). Confirm each against the data or the intent before calling it a bug.
- `--dry-run` / `--count` run **only** SELECTs, **only** over files you map with `--table`. Writes, table functions and anything touching files or the environment are refused.

## Reading a query: grain first

For every CTE or subquery, write down **what one row is**. Most wrong numbers come from a grain change nobody noticed:
1. Grain of each input (one row per order? per order line? per event?).
2. Each join: is the joined key **unique** on the other side? If not, rows multiply (fan-out) and every SUM after it is inflated. Check with `scripts/detect_duplicates.py --key` on the data, or a `count(*) vs count(DISTINCT key)` query.
3. Each filter: which rows does it remove, and is that intended? A WHERE on a LEFT JOINed table (SQ05) silently removes the unmatched rows.
4. Each aggregate: at which grain is it computed, and is it re-aggregated later (average of averages)?

**Prove the output grain** when sample data is available: `--count --grain <key>` reports extra rows if the query multiplies rows. Static analysis cannot see a fan-out (it depends on the data); this check can.

State the grain chain in the analysis: `orders (1/order) → JOIN order_lines (n/order) → SUM(amount) is now per line ✗`.

## Rule catalogue

| Rule | Severity | Pattern | Why it matters | Fix |
|---|---|---|---|---|
| D1–D6 | destructive | DROP, TRUNCATE, DELETE/UPDATE without WHERE, ALTER … DROP, CREATE OR REPLACE, INSERT OVERWRITE | Data loss | Never run without approval and a backup/rollback |
| SQ02 | high | `NOT IN (subquery)` (Snowflake shows it as `<> ALL`) | One NULL in the subquery → zero rows | `NOT EXISTS` |
| SQ04 | high | Join without a condition | Cartesian product | Add `ON`, or write `CROSS JOIN` if intended |
| SQ05 | high | WHERE on a LEFT JOINed table | Silent INNER JOIN | Move the condition into `ON` |
| SQ06 | high | `= NULL`, `<> NULL` | Never true | `IS [NOT] NULL` |
| SQ01 | warn | `SELECT *` | Upstream schema changes flow through | List columns |
| SQ07 | warn | `LIMIT` without `ORDER BY` | Non-deterministic rows | Add `ORDER BY` |
| SQ08 | warn | `DISTINCT` over a join | Hides a fan-out | Fix the join key |
| SQ10 | warn | `AVG(rate)` | Mean of rates ≠ overall rate | `sum(num) / sum(den)` |
| SQ11 | warn | `ts BETWEEN '…' AND 'YYYY-MM-DD'` | Drops the last day after 00:00 | `>= start AND < next_day` |
| SQ03 | perf | Function around a column in a filter/join | No pruning / index | Transform the constant side |
| SQ09 | info | `UNION` | Sort/hash to dedupe | `UNION ALL` if dupes are impossible or wanted |
| SQ12 | info | `ORDER BY` in a subquery without LIMIT | Ignored | Remove |
| SQ13 | info | Division without `NULLIF` | Divide-by-zero | `x / NULLIF(y, 0)` |

## Optimising: measure, then change one thing

1. **Get the plan with real numbers**: `EXPLAIN ANALYZE` (Postgres/DuckDB), query profile (Snowflake), execution details and bytes scanned (BigQuery), Spark UI / `df.explain("formatted")`. Without a measurement, an optimisation is a HYPOTHESIS.
2. Find the dominant cost: full scan where pruning was possible, a spill, a skewed join, an exploding join, repeated scans of the same table.
3. Change **one** thing; re-measure; keep it only if it helped. Report before/after with the same input.
4. Prove the result did not change: row count and a checksum/sums of key columns before vs after (`reconcile.py` on the two outputs).

Usual wins, in order: read fewer columns → filter earlier on partition/cluster columns (SQ03 blocks this) → pre-aggregate before joining → fix fan-out joins → replace `UNION`/`DISTINCT` used as a patch → materialise a reused intermediate.

## Translating between dialects

`--to` uses sqlglot. Its output is **NOT_VERIFIED** until it runs on the target engine, because:
- Functions differ in semantics, not just name (date arithmetic, integer division, NULL ordering, string collation, `LIKE` case-sensitivity).
- Unsupported constructs are listed as warnings — read every one.
- Types differ (Snowflake `NUMBER(38,0)` vs BigQuery `INT64`/`NUMERIC`).
Verify with a row count and key sums on both engines.

## Writing new SQL

- State the output grain in a comment at the top.
- CTEs named for what they hold (`orders_paid_2026`), one step each.
- Explicit column lists; explicit `JOIN … ON`; `UNION ALL` unless dedupe is the point.
- Run it through `sql_check.py` before handing it over, and say which findings remain and why.
- If you could not run it on the user's engine, label it NOT_VERIFIED (rule 2).
