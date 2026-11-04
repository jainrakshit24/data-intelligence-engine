# Incremental loads

Load this for ETL/ELT/CDC designs on tables too large to reload, and for dbt incremental models.

## Contents
- Choosing the change signal
- The watermark pattern
- Late and out-of-order data
- Applying changes idempotently
- Backfills and full refreshes
- Verifying an incremental load

## Choosing the change signal

| Signal | Catches inserts | Catches updates | Catches deletes | Notes |
|---|---|---|---|---|
| Append-only id / timestamp | ✓ | ✗ | ✗ | Only for immutable events |
| `updated_at` column | ✓ | ✓ | ✗ | Only if **every** writer updates it (check triggers, bulk scripts) |
| Partition / file arrival | ✓ | per partition | per partition | Reprocess whole partitions |
| Log-based CDC | ✓ | ✓ | ✓ | `cdc.md` |
| Full snapshot diff | ✓ | ✓ | ✓ | Expensive; good as a periodic safety net |

Verify the signal on the data before trusting it: does `updated_at` change on every update? Profile it, and compare a full extract with the incremental result once (`reconcile.py`).

## The watermark pattern

```sql
-- read
SELECT * FROM source
WHERE updated_at >= :last_watermark - INTERVAL '2 hours'   -- lookback for late commits
  AND updated_at <  :run_upper_bound;                      -- fixed for this run, never now() mid-run
-- after a verified commit
UPDATE load_state SET watermark = :run_upper_bound WHERE table_name = 'orders';
```

- `>=` plus a **lookback**, with dedupe on the key, never misses rows; `>` can skip rows that share the last timestamp.
- Fix the upper bound at the start of the run, so a long run doesn't chase new rows.
- Advance the watermark only after the target commit is verified.

## Late and out-of-order data

- Measure lateness: distribution of `_loaded_at − event_time`. Choose the lookback from its p99, and say so.
- Events later than the lookback need a policy: drop and count, route to a correction job, or periodic restatement of recent partitions.
- For aggregates by event time, published numbers for recent periods **will change**; tell consumers how many days are provisional.

## Applying changes idempotently

```sql
MERGE INTO target t
USING (SELECT * FROM batch QUALIFY row_number() OVER (PARTITION BY id ORDER BY updated_at DESC) = 1) s
ON t.id = s.id
WHEN MATCHED AND s.updated_at >= t.updated_at THEN UPDATE SET …
WHEN NOT MATCHED THEN INSERT …;
```

- Deduplicate the batch first: MERGE fails or is non-deterministic when several source rows match one target row.
- Guard updates with the version/timestamp so an older replay never overwrites newer data.
- Partitioned targets: overwrite the affected partitions instead of row-level MERGE when most rows in them change.

## Backfills and full refreshes

- Parameterise every load by interval, so backfill = the same code over past intervals.
- Backfill in chunks (a month at a time), each verified, so a failure costs one chunk.
- A full refresh needs: the cost, the downtime/swap plan, and a reconciliation of old vs new (`reconcile.py old new --key id --compare all`). Explain every difference before swapping.

## Verifying an incremental load

Periodically (weekly, say) compare the incrementally built table to a full rebuild or a source snapshot on keys and sums:

```bash
python3 scripts/reconcile.py source_snapshot.parquet target_export.parquet --key id --compare all --sum amount
```

Dropped keys = missed inserts or unhandled deletes; changed values = missed updates. Drift found here is the evidence that the change signal is incomplete.
