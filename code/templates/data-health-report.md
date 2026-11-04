# Data health report: <dataset name>

## SUMMARY
`DATA HEALTH: <score>/100 — <STATUS exactly as the script printed it> (<n> of 6 dimensions measured)`

<Why that status, in one sentence. The weakest dimension and the check behind it.>

## DATA QUALITY
| Dimension | Score | Weight | Weakest check |
|---|---|---|---|
| completeness | <s / NOT_VERIFIED> | <w> | <check · column · pass rate> |
| validity | | | |
| uniqueness | | | |
| consistency | | | |
| timeliness | | | |
| volume | | | |

Checks below the floor hidden inside the averages: <list, or "none">.

### Rules used
- From the user / data-context.md: <n> checks
- Inferred (proposals, not confirmed): <n> checks

### Gaps
- NOT EVALUATED: <rule — n of N rows skipped (x%) — why>
- RULE PROBLEMS: <rule — why it did not run>
- Excluded dimensions: <dimension — what rule would measure it>

## FINDINGS
```
FINDING:     <…>
EVIDENCE:    <…>
MEANING:     <…>
CONFIDENCE:  <…>
NEXT CHECK:  <…>
```

## RECOMMENDATION
<Ordered: what to fix first, and where (cleaning, source system, pipeline).>

## NEXT STEPS
<Rules to confirm; offer to save them to data-context.md.>

---
COVERAGE: <rows read>/<total> rows · <sheets> · <files> · strategy: <…> · filters: <…>
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
