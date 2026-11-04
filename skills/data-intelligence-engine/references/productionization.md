# Productionization and pipeline optimization

Load this for PRODUCTIONIZATION ("make this notebook/script a real pipeline", "is this ready for production?") and PIPELINE_OPTIMIZATION ("it's too slow", "it costs too much"). The design properties are in `pipeline-architecture.md`; this module is the gap between "it works on my laptop" and "it runs every day without anyone watching". The workflow is `workflows/productionize.md`.

**Scope:** data pipelines only. Productionizing an ML model (serving, Docker/FastAPI endpoints, model monitoring) is out of scope (decision D1). Do the data side, then say where the boundary is.

## Contents
- The readiness review
- From notebook or script to pipeline
- Configuration and secrets
- Observability
- Testing a pipeline
- Release and rollback
- Making a pipeline faster or cheaper
- What to hand over

## The readiness review

Score each item **met**, **partly** or **missing**, with the evidence. "Met" without evidence is NOT_VERIFIED (rule 2).

| # | Property | Evidence that it is met |
|---|---|---|
| 1 | Idempotent | Re-running one period gives identical output (`reconcile.py run1 run2 --key …` → 0 differences) |
| 2 | Parameterised by interval | No `now()` / `today()` inside the logic; the run date comes in as a parameter (`dag_check.py` AF02, AF06) |
| 3 | Backfillable | A past period rebuilds with the same code and matches what was published |
| 4 | Input contract checked | `quality_checks.py --rules contract.json --fail-on-violation` (or dbt contracts/tests) runs **before** outputs are written |
| 5 | Run accounting | Each run records rows in/out/rejected, duration and watermark (`templates/pipeline-run-accounting.md`) |
| 6 | Failure handling | Retries for transient errors only, timeout, alert to an owner (`dag_check.py` AF04/AF05) |
| 7 | Bad rows quarantined | Rejected rows land in a table with a reason; they are counted, not dropped |
| 8 | Secrets outside code | No credentials in code or config files (`dag_check.py` AF08) |
| 9 | Monitored | Freshness, volume and drift checks scheduled (`anomaly_detection.py`, `drift_check.py`) |
| 10 | Owned and documented | Owner, runbook, consumers, SLA written down (`templates/pipeline-design.md`) |
| 11 | Tested | Unit tests on transformation logic; a sample-data run in CI |
| 12 | Personal data handled | Columns classified; masking, minimisation, retention decided (`privacy-and-pii.md`) |

Report the gaps in order of what breaks first: 1, 4, 6 and 8 before 9–12.

## From notebook or script to pipeline

1. **Separate the steps**: extract, validate, transform, load. Each is a function or task with explicit inputs and outputs. No hidden state between cells.
2. **Remove interactive leftovers**: `display()`, `.head()`, ad-hoc filters, cells run out of order, hard-coded paths.
3. **Make the date a parameter** and derive every window from it.
4. **Make writes idempotent**: overwrite the partition or MERGE on the key, never append blindly.
5. **Validate the input** against the contract before transforming; stop on a break.
6. **Record run accounting** at the end of every run.
7. **Put it under an orchestrator** (`orchestration.md`), or cron for a single job; the code must not care which.
8. **Dependencies pinned** (lockfile or `requirements.txt` with versions), and the runtime reproducible.

Generated code is labelled with how far it was verified: written only (NOT_VERIFIED), parsed (`sql_check.py`, `dag_check.py`), run on sample data, run on real data.

## Configuration and secrets

- Environment-specific values (paths, connection names, schedules) in config or environment variables; code identical across dev, staging and prod.
- Secrets in the platform's secret store (Airflow connections, cloud secret manager, environment injected at runtime). Refer to them by name, never by value, in code, logs or reports (`safe-database-access.md`).
- The pipeline's database role has only the grants it needs: read on sources, write on its own targets.

## Observability

| Signal | Answers | Source |
|---|---|---|
| Run status and duration | Did it run; is it getting slower? | Orchestrator |
| Run accounting | Did it process what it should? | `pipeline-run-accounting.md` block |
| Freshness | Is the output current? | `freshness` rule; newest event time |
| Volume and metric anomalies | Is the output plausible? | `anomaly_detection.py --fail-on-anomaly` |
| Drift | Has the data's shape changed? | `drift_check.py --fail-on major` |
| Contract | Do the agreed rules hold? | `quality_checks.py --fail-on-violation` |

Every alert goes to an owner and says what to look at first. An alert nobody owns is noise.

## Testing a pipeline

- **Unit**: transformation functions or SQL on small fixed inputs with known outputs (dbt unit tests, pytest on fixtures).
- **Contract**: input and output rules (above).
- **Integration**: a full run on a sample in CI; `reconcile.py` input vs output to prove every row is accounted for.
- **Regression**: before a change, compare old and new output on the same input (`pipeline-architecture.md`, "Changing an existing pipeline").
- **Planted defects**: a fixture with known bad rows that the pipeline must quarantine, with exact counts.

## Release and rollback

- Deploy code and schema changes separately where possible; schema changes follow `schema-evolution.md`.
- Ship behind a parallel run: new version writes to a shadow table; reconcile against the current one for a few runs; then switch.
- Rollback = previous code version + re-run of the affected periods (possible only if the pipeline is idempotent and backfillable).

## Making a pipeline faster or cheaper

**Measure before changing anything.** Get per-stage durations and the bytes or rows each stage reads. Optimise the slowest stage first; a 10× win on a stage that takes 2% of the runtime saves nothing.

| Symptom | Likely cause | Check | Fix |
|---|---|---|---|
| Runtime grows with history | Full reload of all history every run | Rows read per run vs rows changed | Incremental load with watermark and lookback (`incremental-loads.md`) |
| Query scans the whole table | No partition or cluster pruning; function on the partition column | EXPLAIN / query profile; `sql_check.py` SQ rules | Filter on the raw partition column; partition or cluster by the common filter |
| One task takes much longer than its siblings | Skew: one key holds most rows | Rows per key / partition | Salt the hot key, or handle it separately (`pyspark.md`) |
| Many tiny files | Small appends; over-partitioning | Files per partition, average file size | Compaction; coarser partitions; fewer, larger writes |
| Join explodes, then dedupes | Join on a non-unique key, fixed with DISTINCT | `sql_check.py --grain`; `reconcile.py` fan-out | Join at the right grain; remove the DISTINCT |
| Same data computed by several jobs | Duplicate logic | Lineage | One shared model, reused |
| Shuffle-heavy Spark stages | Wide joins of two large tables | Spark UI stage metrics | Broadcast the small side; pre-aggregate; align partitioning |
| Warehouse cost spikes | `SELECT *`, repeated full scans, oversized compute | Bytes scanned per query; credits per job | Select needed columns; materialise hot intermediates; right-size compute and auto-suspend |
| Python step is slow | Row-by-row loops; pandas on data larger than memory | Profile the step | Vectorise; push the work into SQL/DuckDB/Polars (`python-data-processing.md`) |

Prove each optimisation:
1. Same output: `reconcile.py before_out after_out --key … --compare all --sum …` shows 0 differences.
2. Faster or cheaper, measured the same way as before, on the same input, more than once.

A faster pipeline that changed the numbers is a regression, not an optimisation.

## What to hand over

- The readiness review table with evidence and gaps.
- The changes made or proposed, each with its verification level.
- Monitoring commands ready to schedule.
- A runbook: how to re-run a period, how to backfill, who owns it, what each alert means.
