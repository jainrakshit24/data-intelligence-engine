# Workflow: productionize a pipeline

For PRODUCTIONIZATION, PIPELINE_OPTIMIZATION and DATA_CONTRACT. Load `references/productionization.md`; add `references/data-contracts.md` and `references/schema-evolution.md` for contracts, and the stack module (`dbt.md`, `orchestration.md`, `pyspark.md`, `python-data-processing.md`) for the code in front of you.

Pick the mode first:
- **Readiness review**: "is this ready for production?" Steps 1–3 and 8.
- **Productionize**: "turn this notebook/script into a pipeline". Every step.
- **Optimize**: "it is too slow / too expensive". Steps 1, 6, 7 and 8.
- **Contract**: "write a contract for this table". Steps 1, 4 and 8.

```
- [ ] 1. Read the code and run the static checkers that apply
- [ ] 2. Readiness review: 12 properties, each met / partly / missing, with evidence
- [ ] 3. Order the gaps by what breaks first
- [ ] 4. Contract: draft from the profile, confirm terms, check recent data against it
- [ ] 5. Make the changes; label each with its verification level
- [ ] 6. Optimize: measure per stage; fix the slowest stage first
- [ ] 7. Prove: reconcile old vs new output = 0 differences; timing measured twice
- [ ] 8. Hand over: review table, changes, monitoring commands, runbook
- [ ] 9. validate-before-delivery.md
```

## Steps

1. **Read and check.** `dag_check.py` for Airflow, `dbt_check.py` for dbt, `sql_check.py` for SQL files. Their findings are evidence for step 2.
2. **Review.** Use the table in `productionization.md`. "Met" needs evidence; without it the item is NOT_VERIFIED.
3. **Prioritise.** Idempotency, input contract, failure handling and secrets first.
4. **Contract.** `profile_dataset.py` → draft `contract.json` (schema, keys, rules, freshness, volume) → confirm units, meaning and change policy with the owner → `quality_checks.py <recent data> --rules contract.json --fail-on-violation`. A term today's data already breaks is either wrong or a known defect: say which.
5. **Change.** The smallest change that closes each gap. Every piece of code says how far it was verified.
6. **Optimize.** Per-stage durations and rows/bytes read first. Then the table in `productionization.md`.
7. **Prove.** `reconcile.py before_out after_out --key … --compare all --sum …` must show no differences, unless a difference was the point. Timing on the same input, more than once.
8. **Hand over.** Include ready-to-schedule monitoring:
   ```bash
   quality_checks.py <output> --rules contract.json --fail-on-violation
   anomaly_detection.py <output> --time <event_time> --complete-through <yesterday> --fail-on-anomaly
   drift_check.py <last_good_snapshot> <output> --fail-on major
   ```
9. **Validate.**

## Never

- Mark a property "met" because the code looks like it does it. Run it, or say NOT_VERIFIED.
- Optimise without proving the output is unchanged.
- Put a credential value in code, config or a report.
- Productionize a model's serving layer: out of scope (D1). Do the data pipeline, then name the boundary.
