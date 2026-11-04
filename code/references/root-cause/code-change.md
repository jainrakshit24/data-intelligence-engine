# Playbook: code change

The output changed after an edit to SQL, a dbt model, a transformation script or a config. Shared method: `../root-cause-investigation.md`.

## Measure
- The change window: commits and deploys between the last good run and the first bad one (`git log --since … --until … -- <paths>`).
- The diff of each candidate commit, limited to the code that builds the affected table.
- The output of the old code and the new code on the **same input**. This is the deciding check.

## Hypotheses and the check that separates them

| Hypothesis | Check | Supports it |
|---|---|---|
| Logic change (filter, join, CASE) | Run old and new SQL on the same input; `reconcile.py old_out new_out --key` | Differences are exactly the rows the new predicate treats differently |
| Join grain changed | `sql_check.py --grain` on the new model | New fan-out or collapse at the declared grain |
| Incremental logic changed | `dbt_check.py` (DB04, DB05, DB07); watermark comparison | `>` instead of `>=`, a missing lookback, a changed `unique_key` |
| Config changed (materialization, schedule, variables) | Config diff; dbt project/YAML/SQL precedence | Model became incremental, or a var changed the window |
| Dependency or engine version | Lockfile diff; engine release notes | Same code, different result after an upgrade |
| Not the code at all | Old code on new input reproduces the change | The input changed: go to the other playbooks |

The last row is the most often skipped. If the old code gives the same "wrong" result on today's input, the edit is innocent.

## Usual fixes
- Revert, or correct forward with a test that captures the case.
- Backfill from the first bad run; verify old vs fixed output with `reconcile.py`.

## Prevention
- Before merging a change to a model: run `sql_check.py` / `dbt_check.py`, then compare old vs new output on a recent day with `reconcile.py` (`pipeline-architecture.md`, "Changing an existing pipeline").
- Grain tests (`unique`, `not_null` on the key) on every model.
