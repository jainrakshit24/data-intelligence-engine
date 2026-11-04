# Playbook: freshness

The data is not as recent as it should be: the newest timestamp is old, today's partition is empty, a dashboard shows yesterday. Shared method: `../root-cause-investigation.md`.

## Measure
- Newest event time and newest load time in the table. Their gap is lag; their distance from now is staleness.
- `anomaly_detection.py --time <event_time> --grain hour` around the gap: did rows stop, or slow down?
- The SLA or freshness rule (`quality_checks.py` `freshness`). Without one, ask what "fresh" means before calling it late.

## Hypotheses and the check that separates them

| Hypothesis | Check | Supports it |
|---|---|---|
| The job did not run | Orchestrator run history for the window | No run record, or "skipped" / "upstream_failed" |
| The job ran but loaded nothing | Run log row counts; target table's load timestamps | Run succeeded with 0 rows written |
| The source is stale | Newest timestamp in the source / landing zone | Source is just as old |
| Late-arriving data | Load time vs event time for recent rows | Event times are recent but loaded hours later; earlier periods filled in on later runs |
| A watermark is stuck | The stored high-water mark vs source max | Watermark has not advanced; a `>` comparison skipped equal timestamps (`incremental-loads.md`) |
| Time-zone shift | Compare UTC and local of the newest rows | Data is there, but shifted by the offset |
| Schedule changed | Orchestrator schedule history, DAG code diff | New cron or `start_date` |

## Usual fixes
- Re-run the missed interval (Airflow backfill / clear the task) once the cause is fixed. Running it before the fix only repeats the failure.
- Move a stuck watermark back to the last verified-complete point, then reload with an idempotent merge.
- Add a lookback window for late data (`incremental-loads.md`).

## Prevention
A freshness check that pages:

```bash
python3 scripts/quality_checks.py table_export.parquet --rules contract.json --fail-on-violation
# contract.json: {"freshness": {"column": "event_ts", "max_age_hours": 6}}
```
