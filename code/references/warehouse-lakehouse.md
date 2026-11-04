# Warehouse and lakehouse design

Load this for WAREHOUSE_DESIGN and LAKEHOUSE_DESIGN, with `pipeline-architecture.md`.

## Contents
- Warehouse, lake or lakehouse
- Dimensional modelling
- Slowly changing dimensions
- Physical design
- Lakehouse table formats
- Design checks

## Warehouse, lake or lakehouse

| | Warehouse (Snowflake, BigQuery, Redshift, Postgres) | Lakehouse (Delta Lake, Apache Iceberg, Apache Hudi on object storage) |
|---|---|---|
| Strength | SQL analytics, concurrency, least operations | Open formats, one copy for SQL + Spark + ML, cheap storage at scale |
| Cost model | Compute per query/warehouse; storage managed | Storage cheap; you run (or rent) the engines |
| Choose when | Mostly SQL consumers; team prefers managed | Large/raw/semi-structured data, ML on the same data, multi-engine, avoiding lock-in |

Many stacks mix them (Iceberg tables queried from Snowflake/BigQuery). Record the choice and the rejected option in an ADR.

## Dimensional modelling

1. **Choose the business process** (orders, payments, sessions).
2. **Declare the grain** in one sentence: "one row per order line per day". Every later decision follows from it; write it in the model's description.
3. **Facts**: numeric measures at that grain, plus foreign keys to dimensions. Additive (amount), semi-additive (balance: do not sum over time), non-additive (ratios: store numerator and denominator).
4. **Dimensions**: descriptive attributes (customer, product, date), one row per member (per version for SCD2), with a surrogate key.
5. **Conformed dimensions**: one `dim_customer` shared by every fact, so numbers agree across marts.

Wide denormalised tables ("one big table") are fine for a single consumer; derive them *from* the star schema so definitions stay in one place.

## Slowly changing dimensions

| Type | Behaviour | Use for |
|---|---|---|
| 0 | Never changes | Original signup date |
| 1 | Overwrite | Corrections, attributes nobody reports historically |
| 2 | New row per change, with `valid_from`, `valid_to`, `is_current` | Attributes reports must see "as it was" (customer segment, region) |
| 3 | Previous value in a column | Rare: one prior value is enough |

SCD2 rules: `valid_to` of the old row = `valid_from` of the new row (half-open intervals); exactly one `is_current` row per natural key (test it); facts join on the surrogate key of the version valid at the fact's time.

## Physical design

- **Partition** big tables by the column most filters use (usually event date). Too many tiny partitions hurt as much as none.
- **Cluster / sort** by the next most filtered columns (Snowflake clustering keys, BigQuery clustering, Redshift sort keys, Delta Z-order/liquid clustering, Iceberg sort order).
- Filters must hit the partition column **unwrapped** — `WHERE date(ts) = …` can prevent pruning (`sql_check.py` SQ03).
- Keep raw history immutable; rebuild marts from it.

## Lakehouse table formats

- Pick one format per platform (Delta Lake or Iceberg; Hudi for heavy upsert/streaming ingestion). All give ACID transactions, schema evolution, time travel and MERGE.
- **Small files** are the main operational problem: schedule compaction (`OPTIMIZE` in Delta, `rewrite_data_files` in Iceberg) and size files to roughly 128 MB–1 GB.
- Expire old snapshots/versions (`VACUUM`, `expire_snapshots`) on a retention you have agreed with compliance — it also limits time travel.
- Medallion layers (bronze/silver/gold) map to raw/staging/marts in `pipeline-architecture.md`.

## Design checks

Before handing over a model:
- [ ] Grain written down and **tested** (unique key test on the grain columns).
- [ ] Every fact's foreign keys resolve (relationship tests; count orphans, don't just fail).
- [ ] Measures labelled additive / semi-additive / non-additive.
- [ ] SCD2 dimensions: one current row per key; no overlapping validity intervals.
- [ ] A reconciliation from source to fact (`reconcile.py`) with every row explained.
