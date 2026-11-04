# Anomaly report: <dataset or pipeline>

## SUMMARY
<One sentence: what changed, by how much, since when.>
<One sentence: the root cause and its grade, e.g. "Most likely X (SUPPORTED, High): Y was checked and ruled out." Or "Not yet confirmed; the deciding check is Z.">

## ANOMALIES
| Period | Series | Value | Expected | Size | Type |
|---|---|---|---|---|---|
| <from the script, exactly> | | | | <z, or % for shifts> | spike / drop / missing period / level shift / drift |

Segments that moved: <segment — share of the change>.
Script and flags: `<the command that produced the table>`

## ROOT CAUSE
**Issue type(s):** <freshness / volume / schema change / pipeline failure / code change / field drift>

**Timeline**
```
<time>  <change or symptom>   (<source of the fact>)
```

**Hypotheses**
| Hypothesis | Check | Result | Grade |
|---|---|---|---|
| | | | SUPPORTED / PARTIALLY_SUPPORTED / REJECTED / NOT_VERIFIED |

**Evidence chain**
1. <step> — <the check that proved it>

## IMPACT
- Rows / periods affected: <n>, <from → to>
- Measures affected: <sum delta, from reconcile.py>
- Downstream: <tables, dashboards, consumers>

## RECOMMENDATION
**Fix:** <specific change>
**Backfill:** <window> — verify with `<reconcile.py command>`
**Prevention:** `<schedulable command that would have caught this>`

## RISKS
<What is still NOT_VERIFIED, and what changes if it turns out otherwise.>

---
COVERAGE: <rows read>/<total> rows · <files> · strategy: <…> · filters: <…>
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
