# Orchestration (Airflow and friends)

Load this for AIRFLOW_DESIGN and for any scheduled pipeline. Examples use Airflow 2.x/3.x TaskFlow; check the user's version (`airflow version`) — imports and defaults differ (Airflow 3 uses `airflow.sdk`, `schedule=` only, and `catchup` defaults to False).

## Contents
- What the orchestrator is for
- Task design
- Scheduling and intervals
- Retries, timeouts, alerts
- Dependencies between pipelines
- A minimal DAG
- Review checklist

## What the orchestrator is for

Ordering, scheduling, retries, alerting and visibility. **Not** heavy computation: push the work to the warehouse, Spark or a container, and let the task trigger and wait. A worker running pandas on 50 GB is a design smell.

## Task design

- **Idempotent**: re-running a task for the same interval produces the same result (MERGE / partition overwrite, `incremental-loads.md`).
- **Atomic**: a task either completes its unit of work or leaves nothing behind (write to temp, then swap).
- **Interval-driven**: use the run's data interval (`data_interval_start`, `data_interval_end`), never `datetime.now()` inside logic — otherwise backfills compute the wrong period.
- **Right-sized**: one task per meaningful, restartable step. Not one task per row; not one task for the whole pipeline.
- **Small XComs**: pass references (table names, paths), not data.
- **No top-level work in DAG files**: no DB queries, API calls or heavy imports at module level — the scheduler parses the file constantly.

## Scheduling and intervals

- A run for interval [start, end) runs **after** the interval ends. Communicate this to consumers.
- `catchup`: decide explicitly. True back-runs every missed interval since `start_date`; False runs only the latest.
- `start_date` fixed in the past (never `now()`), in UTC; set the timezone explicitly if the business schedule is local.
- `max_active_runs=1` for pipelines whose runs must not overlap (incremental loads with watermarks).

## Retries, timeouts, alerts

- `retries` with `retry_delay` and exponential backoff for transient failures; a data-quality failure should not retry.
- `execution_timeout` on every task, so a hung query doesn't hold a slot forever.
- Failure callbacks / notifications to an owner, with the run accounting.
- Deferrable operators/sensors (or `mode="reschedule"`) for long waits, so waiting doesn't occupy a worker slot.

## Dependencies between pipelines

Prefer data-aware triggers (Airflow Datasets in 2.4+, called Assets in 3.x) or a sensor on the upstream table's freshness, over guessing times ("run at 3am because upstream usually finishes at 2"). Record the dependency in the design document.

## A minimal DAG

```python
from datetime import datetime, timedelta
from airflow.sdk import dag, task          # Airflow 2.x: from airflow.decorators import dag, task

@dag(schedule="@daily", start_date=datetime(2026, 1, 1), catchup=False, max_active_runs=1,
     default_args={"retries": 3, "retry_delay": timedelta(minutes=5),
                   "retry_exponential_backoff": True, "execution_timeout": timedelta(hours=1)},
     tags=["orders"])
def orders_daily():
    @task
    def extract(data_interval_start=None, data_interval_end=None):
        # pull rows with updated_at in [start, end) + lookback; write to raw; return the path
        ...

    @task
    def load(path: str):
        # MERGE into staging on order_id; return run accounting (rows in/out/rejected)
        ...

    @task
    def check(accounting: dict):
        # fail the run if contracts break (volume range, key uniqueness)
        ...

    check(load(extract()))

orders_daily()
```

This skeleton loads without import errors or deprecation warnings in Airflow 3.3 (checked with `DagBag`). Its task bodies are placeholders, so a version filled in for the user is NOT_VERIFIED until it runs in their Airflow (`airflow dags test orders_daily 2026-01-01`).

## Review checklist

Run the static checker first; it covers most of this list without importing the file:

```bash
python3 scripts/dag_check.py dags/            # AF01–AF13; --fail-on high for CI
```

It never imports or runs the DAG (importing executes top-level code). Secret values it finds are never printed. AF07 (`schedule_interval`) is a TypeError on Airflow 3, not just a warning. AF13 lists Airflow 2 import paths that Airflow 3 deprecates (`airflow.decorators`, core `operators`/`sensors` now in `airflow.providers.standard`). Then check by hand what it cannot see:

- [ ] No top-level queries or heavy imports.
- [ ] Every task idempotent and interval-driven; no `now()` in logic.
- [ ] `start_date` static; `catchup` and `max_active_runs` chosen deliberately.
- [ ] Retries only for transient errors; timeouts everywhere.
- [ ] Alerts reach an owner.
- [ ] Data checks gate publication.
- [ ] Secrets come from connections/secret backends, never from code.
