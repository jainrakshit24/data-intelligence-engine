# Workflow: investigate an anomaly

For ANOMALY_DETECTION, DATA_DRIFT, SCHEMA_ANALYSIS (when something broke) and PIPELINE_DEBUGGING. Load `references/root-cause-investigation.md`, plus `references/anomaly-detection.md` (change over time) or `references/data-drift.md` (two snapshots), and the playbook for each issue type found in step 3.

```
- [ ] 1. Intake: what, how far off, since when, what changed, what access exists
- [ ] 2. Reproduce the symptom with a script (numbers, not the report of it)
- [ ] 3. Classify the issue type(s); load each playbook
- [ ] 4. Blast radius: upstream and downstream lists
- [ ] 5. Change timeline: every known change and the first bad period on one axis
- [ ] 6. Upstream walk: find the first hop where the symptom appears
- [ ] 7. Hypotheses: list all that fit; one separating check each; run; grade
- [ ] 8. Impact in numbers; fix + backfill plan; prevention command
- [ ] 9. Report (templates/anomaly-report.md)
- [ ] 10. validate-before-delivery.md
```

## Steps

1. **Intake.** Ask only what the data cannot tell you (what changed, what access exists). Assume and state the rest.
2. **Reproduce.**
   - Over time: `python3 scripts/anomaly_detection.py <data> --time <event_time> [--metric …] [--nulls …] --by <segment>`. Add `--complete-through` if the latest period may still be loading.
   - Two snapshots: `python3 scripts/drift_check.py <before> <after>`.
   - Input vs output of a step: `python3 scripts/reconcile.py <in> <out> --key <key> [--sum <measure>]`.

   If the symptom does not reproduce, that is the first finding. Report it and stop, or ask for the data that shows it.
3. **Classify** with the table in `root-cause-investigation.md`. Start from the most upstream type.
4. **Blast radius.** `sql_check.py --lineage` on the queries involved, `dbt_check.py` on a dbt project, `dag_check.py` on DAGs; plus what the user names (dashboards, exports).
5. **Timeline.** A change that comes after the first bad period is rejected now.
6. **Upstream walk.** Same script, one hop up, until the symptom is absent. The cause lives between the last clean hop and the first bad one.
7. **Hypotheses.** For each: the check, its result, its grade. Unreachable checks are written out as commands for the user and graded NOT_VERIFIED.
8. **Impact, fix, prevention.** Impact in rows, periods and sums. Fix with a backfill window and the `reconcile.py` command that will prove it worked. Prevention as a schedulable command.
9. **Report.** One root cause, or "most likely" with what would settle it. Never more certain than the grades allow.
10. **Validate.**

## Multi-intent example

"My daily customer pipeline has 30% fewer records, find out why" → DATA_QUALITY + ANOMALY_DETECTION + PIPELINE_DEBUGGING:
1. `anomaly_detection.py customers.parquet --time created_at --by source_system`: level shift −30% from 6 April, 95% in one source.
2. Upstream walk: that source's landing files are complete → loss is inside the pipeline.
3. `reconcile.py landing.parquet customers.parquet --key customer_id`: the dropped keys all have NULL `country`.
4. Code-change playbook: a commit on 5 April added `INNER JOIN dim_country`. Old SQL on today's input keeps the rows (SUPPORTED); source sent less (REJECTED by step 2); real drop (REJECTED: landing is complete).
5. Fix `LEFT JOIN` + backfill from 6 April; prevention `anomaly_detection.py … --by source_system --fail-on-anomaly`.

## Never

- Call a cause CONFIRMED on timing alone.
- Stop at "it's all in segment X" without explaining why X changed.
- Propose a fix without a backfill plan for the periods already published.
- Print raw rows or key values while investigating; write them to a file with the SQL the scripts print.
