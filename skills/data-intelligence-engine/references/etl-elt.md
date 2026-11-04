# ETL and ELT

Load this for ETL_DESIGN and ELT_DESIGN, with `pipeline-architecture.md`.

## Contents
- Which one
- ELT pattern
- ETL pattern
- Extraction rules
- Loading rules
- Common traps

## Which one

| Choose | When |
|---|---|
| **ELT** (load raw, transform in the warehouse) | A cloud warehouse/lakehouse exists; transformations are SQL-expressible; you want replay from raw; analysts own the logic (dbt) |
| **ETL** (transform before loading) | PII must be masked or dropped before it lands; the target is not a warehouse (an API, an operational DB); heavy non-SQL processing (parsing documents, ML features); the source volume must be reduced before transfer |

Most modern stacks are ELT with a thin ETL step where compliance requires it. Say which, and why, in an ADR.

## ELT pattern

```
extract (EL tool / script) → raw schema (append, + _loaded_at, _batch_id)
  → staging models (type, rename, dedupe to one row per key)
  → intermediate models (joins, business logic)
  → marts (facts, dimensions)            — all in SQL, versioned, tested (dbt.md)
```

## ETL pattern

```
extract → validate (schema, keys, volume) → transform (typed code, tested) → write to a temp/staging target
  → verify (reconcile counts) → atomic swap / MERGE into the target
```

Write to a staging location and swap atomically (rename, partition exchange, `MERGE`), so readers never see a half-written table.

## Extraction rules

- Extract **what changed**, not everything, once a table is large (`incremental-loads.md`, `cdc.md`).
- Record the **watermark** reached (max `updated_at`, LSN, file name, offset) in a state table, and only advance it after the load commits.
- Pull from replicas or exports, not the primary OLTP database, for big reads.
- Keep the raw response/file. Re-extraction is often impossible later.

## Loading rules

- Idempotent: `MERGE` on the business key, or `DELETE` + `INSERT` of the exact partition in one transaction, or partition overwrite.
- Schema changes: decide per source — fail, add new columns, or ignore (`schema` section of the design). Never silently drop a column.
- Types: parse with explicit formats (dates, decimals, currencies). A cast that turns bad values into NULL must be counted, not hidden.

## Common traps

| Trap | Symptom | Prevention |
|---|---|---|
| Watermark advanced before commit | Rows lost after a failed run | Advance in the same transaction, or after a verified commit |
| `>` on a timestamp watermark | Rows with the same timestamp as the last max are skipped | `>=` with dedupe on key, or a lookback window |
| Time zones | Off-by-hours, duplicates around DST | Store UTC; convert at the edge; state the business time zone |
| Re-running a day appends again | Doubled totals | Partition overwrite / MERGE |
| Hard deletes in the source | Rows live forever in the target | CDC, periodic full key reconciliation, or soft-delete flags |
| Join to a dimension that is not unique | Inflated totals | Test uniqueness; `reconcile.py` shows fan-out |
