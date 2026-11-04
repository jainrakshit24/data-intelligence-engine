# Playbook: pipeline failure

A job errored, timed out, retried, or finished "successfully" with partial output. Shared method: `../root-cause-investigation.md`.

## Measure
- The orchestrator's run record: status, start/end, attempt number, the failing task.
- The error itself: first error in the log, not the last. Later errors are usually consequences.
- Output completeness: `reconcile.py` against the input, or row counts per partition against the previous run.

## Hypotheses and the check that separates them

| Hypothesis | Check | Supports it |
|---|---|---|
| Transient (network, lock, throttling) | Error class; same task succeeded on retry | Timeout / connection reset; the retry passed |
| Resource limit | Memory/disk metrics; OOM-killed; spill errors | Fails at the same stage on large days only |
| Data that breaks the code | Error names a value or a cast; `quality_checks.py` on the input | A new null, type or encoding in the failing partition |
| Upstream not ready | Sensor or dependency status; source freshness | Ran before the source landed |
| Credentials or permissions | Auth error; secret rotation date | Started exactly at a rotation |
| Partial write after failure | Output rows for the run vs expected; non-idempotent writes | Rows from the failed attempt remained, then the retry added them again |
| Code or dependency change | Deploy history; library versions | First failing run follows a deploy (then `code-change.md`) |

## Usual fixes
- Make the write idempotent before re-running: overwrite the partition or merge on the key, never plain append (`etl-elt.md`).
- Re-run the failed interval; verify with `reconcile.py`.
- For data that breaks the code: quarantine the bad rows (write them to a reject table with a reason), don't drop them silently.

## Prevention
- Retries with backoff, a timeout and an alert on final failure (`orchestration.md`; `dag_check.py` AF04/AF05).
- Run-accounting after each run (`templates/pipeline-run-accounting.md`): rows in, out, rejected, and a correctness gate.
