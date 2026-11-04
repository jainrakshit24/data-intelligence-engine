# Data profile: <dataset name>

> Fill every `<…>`. Delete sections that do not apply; do not leave them empty.

## SUMMARY
<2–4 sentences: what the data is, its grain, and the 1–3 things anyone must know before using it.>

## DATASET PROFILE
| | |
|---|---|
| Source | `<path or table>` (<format>, <size>) |
| Rows × columns | <rows> × <columns> |
| Grain | One row = <…> · key `<col>` — <unique / N repeated values> |
| Period | <earliest> → <latest> (`<date column>`) |
| Sheets / files | <read> of <total> |

### Columns
| Column | Inferred type | Missing (null + blank/placeholder) | Notes |
|---|---|---|---|
| <col> | <type> | <x% + n> | <trigger, or "—"> |

## FINDINGS
<One block per finding that matters. Order by what the reader must act on first.>

```
FINDING:     <observation with number, base and period>
EVIDENCE:    <script / query that produced it>
MEANING:     <INTERPRETATION or HYPOTHESIS — …>
CONFIDENCE:  <High | Medium | Low> — <why>
NEXT CHECK:  <the one check that would move it up the ladder>
```

## PRIVACY
<Columns classed as identifiers / quasi-identifiers / free text with identifiers. No values.>

## RISKS
<What would go wrong if someone used this data as-is.>

## NEXT STEPS
<Cleaning proposal? Quality rules to confirm? Questions for the data owner?>

---
COVERAGE: <rows read>/<total> rows · <sheets> · <files ok>/<files total> · strategy: <…> · filters: <…>
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
