# Workflow: analyse or optimise SQL

For SQL_ANALYSIS and SQL_OPTIMIZATION. Load `references/sql-intelligence.md` and `references/safe-database-access.md`.

```
- [ ] 1. sql_check.py --dialect <engine>: reads/writes, destructive statements, findings
- [ ] 2. Write the grain chain (each CTE/subquery: one row = ?)
- [ ] 3. Confirm or reject each finding against intent and data
- [ ] 4. Optimisation only: get a measured plan; find the dominant cost
- [ ] 5. Change one thing; re-measure; prove the output is unchanged
- [ ] 6. Report: findings graded, before/after numbers, remaining risks
- [ ] 7. validate-before-delivery.md
```

## Steps

1. **Check.** `python3 scripts/sql_check.py query.sql --dialect <engine>`. Destructive statements are reported first; nothing is run.
2. **Grain chain.** For "why is this number wrong?", the answer is usually here: a fan-out join, a LEFT JOIN turned INNER, a filter in the wrong place.
3. **Confirm findings.** A finding is a pattern. Confirm with data where you can:
   - fan-out / DISTINCT-over-join → `detect_duplicates.py --key` on the joined table's key;
   - NOT IN → count NULLs in the subquery column;
   - wrong totals → `reconcile.py` between the input and the output at the same grain.
   Grade each: SUPPORTED, REJECTED (intended behaviour), NOT_VERIFIED (no data reachable).
4. **Measure.** Ask for or run `EXPLAIN ANALYZE` / the query profile. No plan → recommendations are HYPOTHESES and labelled so.
5. **One change at a time.** Same input, before/after timing or bytes, and an output comparison (row count + key sums, or `reconcile.py old new --key … --compare all`). An optimisation that changes results is a bug.
6. **Report.** For each change: what, why (evidence from the plan), measured effect, and result equality.
7. **Validate.**

For a dialect translation: `--to <engine>`, read every warning, and keep the result NOT_VERIFIED until it has run on the target with matching counts and sums.
