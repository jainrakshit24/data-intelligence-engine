# Playbook: schema change

A column was added, removed, renamed or retyped upstream, and something downstream broke or quietly changed. Shared method: `../root-cause-investigation.md`; change classes in `../data-drift.md` and `../schema-evolution.md`.

## Measure
- `drift_check.py <before> <after>`: removed and added columns, type-family changes, possible renames.
- `quality_checks.py <after> --rules contract.json`: which contract terms the new shape breaks, with failing row counts.
- Downstream: `sql_check.py --lineage` on each consumer query (or `dbt_check.py` on the project) to list which consumers read the changed column.

## Hypotheses and the check that separates them

| Hypothesis | Check | Supports it |
|---|---|---|
| Upstream renamed a column | `drift_check.py` possible rename; producer's changelog | Same type, missing share and distinct ratio under a new name |
| Upstream changed a type | Type family change; `quality_checks.py` `schema` rule failures | e.g. quantity went from digits to words; IDs gained a prefix |
| `SELECT *` picked up a new column | Consumer SQL (`sql_check.py` SQ01) | A positional insert or a fixed-width target shifted |
| Loader inferred a different type | Loader's schema inference settings; a file whose first rows differ | Same source, different inferred type on this run |
| Silent NULLs, not an error | Missing share before vs after (`drift_check.py`) | A renamed column read as NULL by a tolerant reader |

## Usual fixes
- Map the new name or type explicitly in the staging layer, so one place absorbs the change.
- Rebuild affected downstream periods; verify with `reconcile.py`.
- Agree on a deprecation window with the producer (`schema-evolution.md`).

## Prevention
A contract with `schema` and `schema_strict` checked before the load (`data-contracts.md`):

```bash
python3 scripts/quality_checks.py landing/today.csv --rules contract.json --fail-on-violation \
  && run_load || echo "contract broken: load stopped"
```
