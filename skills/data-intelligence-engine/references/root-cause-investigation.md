# Root-cause investigation

Load this for PIPELINE_DEBUGGING, and for any "why did the data change" question after an anomaly, drift or failed check. It is the shared method; each issue type has a playbook in `references/root-cause/`. The workflow is `workflows/investigate-anomaly.md`; the report is `templates/anomaly-report.md`.

## Contents
- The rule this module enforces
- Step 1: intake
- Step 2: classify the issue type
- Step 3: the three shared checks
- Step 4: hypotheses and the evidence ladder
- Step 5: the report
- When you cannot reach the system
- Anti-patterns

## The rule this module enforces

A cause is CONFIRMED only when a check you ran supports it **and** the competing explanations were checked and rejected. Timing alone ("the deploy was at 09:00, the drop at 09:15") is a HYPOTHESIS. Write "consistent with", never "caused by", until the check is done (rule 1).

## Step 1: intake

Get, or assume and state:
1. **What** is wrong, in numbers: which table or metric, how far off, compared with what.
2. **Since when.** The first bad period, not the day someone noticed.
3. **What is known to have changed**: deploys, config, source systems, schedules, upstream owners.
4. **What access exists**: data files, warehouse, logs, git, orchestrator UI. This decides which checks can run (see "When you cannot reach the system").

Then measure the symptom yourself before trusting the report of it: `anomaly_detection.py` for "fewer/more/missing", `drift_check.py` for "looks different", `reconcile.py` for "input and output disagree". A symptom that does not reproduce is the first finding.

## Step 2: classify the issue type

| Symptom | Issue type | Playbook |
|---|---|---|
| Table not updated; newest timestamp is old | Freshness | `root-cause/freshness.md` |
| Row count jumped or dropped; a partition is short or empty | Volume | `root-cause/volume.md` |
| Column missing, renamed, retyped; query errors on a column | Schema change | `root-cause/schema-change.md` |
| Job failed, retried, timed out, or wrote partially | Pipeline failure | `root-cause/pipeline-failure.md` |
| Output changed right after a SQL / dbt / code edit | Code change | `root-cause/code-change.md` |
| Values shifted: null rate, mean, category mix, units | Field drift | `root-cause/field-drift.md` |

Several types at once is normal: a schema change upstream causes a pipeline failure, which causes a freshness gap. Load each playbook that applies. Start with the most **upstream** one.

## Step 3: the three shared checks

Every playbook runs these.

**Blast radius.** What feeds this table, and what reads it? For SQL, `sql_check.py --lineage` gives the tables and columns a query reads. For dbt, `dbt_check.py` and `ref()` graph. For Airflow, the DAG's task dependencies. Write two lists, *upstream* and *downstream*. Downstream decides the impact section; upstream decides where to look.

**Change timeline.** Put every known change and the symptom on one time axis, at the finest grain available:

```
2026-04-05 22:10  CRM export job switched to v2 API        (deploy log)
2026-04-06 00:00  first period with North = 0 rows         (anomaly_detection.py --by region)
2026-04-06 06:00  daily_orders dbt run succeeded            (orchestrator)
```

A cause must come **before** its effect. A change after the symptom began is rejected outright.

**Upstream walk.** Check the same symptom one hop up, then the next, until you find the first place it appears. If the source is also short, the pipeline is innocent. If the source is complete and the output is short, the loss is between them: `reconcile.py source output --key …` says where every row went.

## Step 4: hypotheses and the evidence ladder

List every hypothesis that fits the timeline, not just the first one. For each, name the check that would separate it from the others, run it, and grade the result:

| Grade | Meaning |
|---|---|
| SUPPORTED | The check came out as this hypothesis predicts, and not as the others predict |
| PARTIALLY_SUPPORTED | Fits, but the check cannot exclude a competitor |
| REJECTED | The check contradicts it |
| NOT_VERIFIED | The check could not be run (no access). It stays NOT_VERIFIED in the final report |

A root cause is CONFIRMED only when exactly one hypothesis is SUPPORTED and the rest are REJECTED. Otherwise write "most likely", give the confidence and say which check would settle it.

## Step 5: the report

Five sections, always (`templates/anomaly-report.md`):

1. **Root cause**: what happened, when, at which hop. Its grade and confidence.
2. **Evidence chain**: each step with the check that proved it (command, query, log line).
3. **Impact**: rows, periods, sums and downstream tables affected, in numbers.
4. **Fix**: the specific change, plus a **backfill plan** for the bad periods (reprocess window, how to verify with `reconcile.py` afterwards).
5. **Prevention**: the monitor or contract that would have caught it, as a runnable command (`anomaly_detection.py --fail-on-anomaly`, `quality_checks.py --fail-on-violation`, `drift_check.py --fail-on major`).

## When you cannot reach the system

Say so up front (rule 2). Then:
- Still classify, list hypotheses and build the timeline from what the user gave.
- For each hypothesis, write the **exact query or command** that would test it, for the user to run.
- Grade those hypotheses NOT_VERIFIED. Never upgrade one because it is the most plausible.
- If the user runs the check and pastes the result, grade it then.

## Anti-patterns

- **First plausible story.** A deploy happened, so the deploy did it. Check the timeline and the upstream walk first.
- **Stopping at the segment.** "It is all North" is where, not why.
- **Fixing without backfilling.** The pipeline is fixed but six days of bad data stay downstream.
- **No prevention.** The same incident returns next quarter.
- **Echoing identifiers.** Investigate with counts and keys written to files, not printed rows (rule 4).
