# Change data capture (CDC)

Load this for CDC_DESIGN, with `incremental-loads.md`.

## Contents
- When CDC is worth it
- Log-based vs query-based
- The initial snapshot and the handoff
- Applying the change stream
- Deletes
- Schema changes
- Operating it

## When CDC is worth it

Use CDC when you need deletes, every intermediate update, low latency, or less load on the source than repeated queries. If an `updated_at` column is reliable, deletes don't matter and hourly is fine, query-based incremental loading is simpler.

## Log-based vs query-based

| | Log-based (WAL / binlog / redo; e.g. Debezium, cloud-native CDC) | Query-based (poll `updated_at`) |
|---|---|---|
| Deletes | ✓ | ✗ (needs soft deletes or diffing) |
| Every intermediate change | ✓ | ✗ (only the latest state at poll time) |
| Source load | Low (reads the log) | Queries on the source |
| Ordering | Log position (LSN / binlog offset) | Timestamp, ties possible |
| Setup | Needs log access, replication slots/permissions | Just a read query |
| Risk | Unconsumed replication slot can fill the source disk (Postgres) | Missed changes if a writer forgets `updated_at` |

## The initial snapshot and the handoff

1. Record the log position **before** the snapshot starts.
2. Take a consistent snapshot.
3. Stream changes from the recorded position.
4. Apply snapshot + changes idempotently, so changes that overlap the snapshot are harmless.

Tools like Debezium do this for you; if hand-rolled, state the consistency mechanism explicitly.

## Applying the change stream

Each event carries: operation (c/u/d/r), key, after-image (and before-image), source position, commit timestamp.
- **Order by source position**, not by arrival time or a wall-clock column.
- Apply idempotently: keep `_source_position` on each target row and ignore events with an older position.
- Batch per key: within a batch keep only the last event per key (QUALIFY on position).
- Keep the raw change log (bronze). It is the replay source and the audit trail.
- Exactly-once end to end is rare; design for **at-least-once delivery + idempotent apply**.

## Deletes

- Hard delete in the target, or soft delete (`_is_deleted`, `_deleted_at`)? Soft delete keeps history and supports audits; downstream models must filter it.
- Kafka tombstones (null value) follow delete events for compaction; don't treat them as data.
- SCD2 history (`warehouse-lakehouse.md`) closes the current version on delete.

## Schema changes

A source column added, renamed or retyped arrives as a changed event schema. Decide per table: auto-add nullable columns; fail on type narrowing or drop; never silently map a renamed column to NULL. Use a schema registry where the stack has one.

## Operating it

Monitor: consumer lag (time and position), replication slot size (Postgres), error/dead-letter counts, and a **daily reconciliation** of source vs target counts per key range (`reconcile.py` on exports). CDC that is "running" can still be silently missing a table.
