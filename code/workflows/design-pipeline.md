# Workflow: design a pipeline

For PIPELINE_DESIGN, ETL_DESIGN, ELT_DESIGN, CDC_DESIGN, TRANSFORMATION, WAREHOUSE_DESIGN, LAKEHOUSE_DESIGN, DBT_DESIGN, AIRFLOW_DESIGN and PYSPARK_DESIGN. Load the references the router names, plus `references/pipeline-architecture.md` when the request is a whole pipeline rather than one component (a single dbt project or DAG under review needs only its own module).

```
- [ ] 1. Requirements table (pipeline-architecture.md) — numbers, or stated assumptions
- [ ] 2. Profile a sample of each source (profile-dataset.md) if one is reachable
- [ ] 3. Choose: batch/stream, ETL/ELT, change signal, layers, tools — an ADR for each real choice
- [ ] 4. Model: grain of every output table, keys, SCD types
- [ ] 5. Design quality gates, run accounting and failure handling
- [ ] 6. Write the code skeleton(s) the user asked for
- [ ] 7. Verify as far as possible: sql_check.py, parse/compile, run on a sample, reconcile.py
- [ ] 8. Fill templates/pipeline-design.md (+ templates/architecture-decision.md per ADR)
- [ ] 9. validate-before-delivery.md
```

## Steps

1. **Requirements.** Ask only for what changes the design and cannot be assumed (freshness, volume order of magnitude, whether deletes matter). Assume the rest and write the assumption down.
2. **Look at the data.** If a source extract or sample is available, profile it. Its keys, nulls, duplicates and date formats shape staging logic. A design based on no data says so in RISKS.
3. **Choices.** One line per decision with the rejected alternative. Default to the simplest stack the team already runs.
4. **Model.** Grain sentence per table. Unique key per grain. Which dimensions keep history.
5. **Gates and accounting.** Which checks stop the run (schema, key uniqueness, volume range, freshness); which only warn; where rejected rows go; what each run logs (`templates/pipeline-run-accounting.md`).
6. **Code.** Only what was asked. Each file starts with a comment stating its grain/purpose.
7. **Verify.** Climb as high as the environment allows and label the result:

| Level | How | Label |
|---|---|---|
| Written | — | NOT_VERIFIED |
| Parsed | `sql_check.py --dialect <engine>`; `python -m py_compile`; `dbt parse` | parses |
| Runs on sample | `sql_check.py --table … --count --grain <key>`; local Spark/DuckDB on fixture data | runs on sample data, grain holds |
| Reconciled | `reconcile.py` source vs output on real or realistic data | reconciled: every row explained |

8. **Document.** Fill the template; link ADRs.
9. **Validate.** G2 (execution) is the gate designs fail most: no "this pipeline handles X" for a path that never ran.

## Stop and say so when

- The freshness or correctness requirement is contradictory (real-time and exactly reproducible history from a source with hard deletes and no CDC). Name the conflict and the options.
- A choice depends on something only the user knows (budget, team skills, compliance). Give the options with trade-offs and a default.
