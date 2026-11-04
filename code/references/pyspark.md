# PySpark

Load this for PYSPARK_DESIGN. Assumes Spark 3.x; Adaptive Query Execution (AQE) is on by default since Spark 3.2.

## Contents
- Is Spark needed?
- Writing jobs
- Joins and skew
- Partitions and files
- Reading the plan
- Testing

## Is Spark needed?

A single machine with DuckDB or Polars handles hundreds of GB on fast disks. Recommend Spark when data is beyond one machine, already lives in a Spark platform (Databricks, EMR, Dataproc), or must share a lakehouse with other Spark jobs. Say which reason applies.

## Writing jobs

- Use DataFrame / Spark SQL built-in functions. Python UDFs move every row through Python and block optimisation; if unavoidable, use vectorised `pandas_udf`.
- Select columns early; filter early on partition columns so files are skipped.
- No `collect()` / `toPandas()` on large data; aggregate first.
- Explicit schemas when reading CSV/JSON (`schema=`), not `inferSchema` on large inputs — inference costs a pass and guesses wrong on dirty data.
- Parameterise by date interval; write with partition overwrite (`spark.sql.sources.partitionOverwriteMode=dynamic`) or MERGE on Delta/Iceberg, so reruns are idempotent.

## Joins and skew

- Small dimension (≲ tens of MB): broadcast it (`F.broadcast(dim)`); `spark.sql.autoBroadcastJoinThreshold` defaults to 10 MB.
- Skew: one key holding a large share of rows makes one task run for hours. AQE's skew join (`spark.sql.adaptive.skewJoin.enabled`) splits large partitions; for extreme skew, salt the key.
- Check key uniqueness on the side that should be unique before joining; a many-to-many join is the usual source of exploding row counts (`reconcile.py` shows fan-out).

## Partitions and files

- Shuffle partitions: AQE coalesces small ones; start from the default and tune by observed task sizes (aim for roughly 100–200 MB per task).
- Output files: avoid thousands of tiny files — `repartition` by the partition column before writing, or compact afterwards (`OPTIMIZE` on Delta). `coalesce(n)` reduces files without a shuffle but can create skewed tasks.
- Partition output by a low-cardinality column used in filters (date). Never by a high-cardinality id.
- `cache()` only data reused several times, and `unpersist()` it.

## Reading the plan

`df.explain("formatted")` before running, Spark UI after. Look for: `BroadcastHashJoin` vs `SortMergeJoin`, `PartitionFilters` present on scans, unexpected `CartesianProduct`, large `Exchange` (shuffle) volumes, skewed task durations in the stage view. An optimisation claim needs before/after stage times on the same input.

## Testing

- Unit-test transformations as functions `DataFrame -> DataFrame` on tiny local DataFrames (`SparkSession.builder.master("local[2]")`), with `pyspark.testing.assertDataFrameEqual` (Spark 3.5+).
- Test the edge cases from the profile: nulls in keys, duplicates, placeholders, mixed date formats.
- Code that was not run on a Spark session is NOT_VERIFIED.
