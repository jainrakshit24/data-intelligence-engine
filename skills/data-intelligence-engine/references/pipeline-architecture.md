# Pipeline architecture

Load this for PIPELINE_DESIGN (and with `etl-elt.md` for ETL/ELT). The workflow is `workflows/design-pipeline.md`; the output is `templates/pipeline-design.md`.

## Contents
- Requirements before boxes
- The properties every pipeline needs
- Batch, micro-batch or streaming
- Layers
- Verification: account for every row
- Failure handling
- Changing an existing pipeline
- What to hand over

## Requirements before boxes

Get these numbers before choosing tools. Missing ones are assumptions, stated as such:

| Question | Why it decides the design |
|---|---|
| Sources: what, how many, how they change (append-only, updates, deletes) | Full vs incremental vs CDC |
| Volume: rows/day now and in a year; largest table | Single-node (DuckDB/Polars) vs distributed (Spark) |
| Freshness: how stale may the output be? | Daily batch vs hourly vs streaming |
| Consumers: dashboards, ML, reverse-ETL, APIs | Output shape, SLAs, contracts |
| Correctness: may numbers change after publication? | Late data, restatement, idempotency |
| Existing stack and team skills | The best design the team can run beats the ideal one |
| Compliance: PII, residency, retention | Where data may land, masking, deletion |

**Default to the simplest design that meets the freshness and volume numbers.** A daily SQL job in the existing warehouse beats a streaming platform nobody asked for.

## The properties every pipeline needs

1. **Idempotent.** Running a load twice for the same period gives the same result. Use MERGE on a key, or overwrite a partition — never blind INSERT of a period that may already be there.
2. **Restartable.** A failed run can be re-run from the failed step without manual clean-up.
3. **Backfillable.** Any past period can be rebuilt with the same code (parameterise by date/interval; no `now()` buried in the logic).
4. **Observable.** Each run records rows in, rows out, rows rejected and why, duration, and the watermark it reached (`templates/pipeline-run-accounting.md`).
5. **Contracted.** Inputs are checked (schema, keys, volume) before outputs are written; a broken input stops the run instead of publishing wrong numbers.

## Batch, micro-batch or streaming

| Freshness needed | Choice | Typical tools |
|---|---|---|
| Hours–daily | Batch | Warehouse SQL / dbt, orchestrated by Airflow, Dagster, cron |
| Minutes | Micro-batch | Incremental dbt on a short schedule, Spark Structured Streaming with triggers, Snowflake Dynamic Tables, BigQuery scheduled queries |
| Seconds | Streaming | Kafka + Flink / Spark Structured Streaming / Kafka Streams |

Streaming multiplies operational cost (state, ordering, exactly-once, replays). Recommend it only when a consumer acts within seconds.

## Layers

Name layers by contract, not by fashion:
- **Raw / bronze**: as received, append-only, with load metadata (`_loaded_at`, `_source_file`, `_batch_id`). Never edited. It is the replay source.
- **Staging / silver**: typed, deduplicated, renamed, with one row per business key at a stated grain. Quality checks run here.
- **Marts / gold**: modelled for consumers (facts and dimensions, `warehouse-lakehouse.md`), with documented grain and owners.

## Verification: account for every row

After each stage — and always when a number "looks off" — reconcile input against output:

```bash
python3 scripts/reconcile.py staging_orders.parquet fct_orders.parquet --key order_id --compare all --sum amount
```

It splits the difference into dropped keys, new keys, collapsed duplicates, fan-out from joins, null keys and changed values, and splits each `--sum` delta the same way. Every row and every unit of the sum is attributed. A fan-out line means a join on a non-unique key: totals over the output are inflated.

## Failure handling

- **Fail loudly on contract breaks** (schema change, key no longer unique, volume outside range). Do not "continue with warnings" into published tables.
- **Quarantine bad rows** to a reject table with the reason, and count them in run accounting.
- **Retries** for transient errors only (network, lock timeouts), with backoff and a cap; never retry a data error.
- **Alerting** goes to an owner, with the run accounting attached.

## Changing an existing pipeline

Before modifying a model, job or schema that others read:
1. **Blast radius.** List what reads it downstream (dbt `--select model+`, lineage from `sql_check.py --lineage`, the orchestrator's dependencies, dashboards) and what it reads upstream.
2. **Before/after checks.** Write 3–5 queries whose results must not change (row count, key uniqueness, totals of the main measures, counts per important category) and 1–2 whose change is the point of the edit. Run them on the old and new output — or `reconcile.py old new --key … --compare all --sum …`.
3. **Explain every difference** before switching consumers to the new version.

## What to hand over

`templates/pipeline-design.md`, filled in, plus an ADR (`templates/architecture-decision.md`) for each choice with a real alternative. Any code is labelled with how far it was verified: written only (NOT_VERIFIED), parsed (`sql_check.py`), run on sample data, or run on real data.
