# Cleaning report: <dataset name>

## SUMMARY
<rows before → rows after; how many values changed; what was deliberately left alone.>

## ORIGINAL (unchanged)
| | |
|---|---|
| Path | `<original path>` |
| Size · SHA-256 before | <bytes> · `<hash>` |
| Size · SHA-256 after | <bytes> · `<hash>` — <identical / ✗ CHANGED> |

## CHANGES APPLIED
| # | Column | Issue (evidence) | Change | Rows affected | Approved by |
|---|---|---|---|---|---|
| 1 | <col> | <trigger + count> | <what> | <n (x%)> | <user, date / data-context.md policy> |

## CHANGES PROPOSED BUT NOT APPLIED
| Column | Issue | Why not applied |
|---|---|---|
| <col> | <…> | <needs a business decision / not approved / out of scope> |

## IMPLEMENTATION
- SQL: `<clean_<name>.sql>` — reproduces the output from the original.
- Output: `<name>.cleaned.csv`

## VALIDATION
| Check | Result |
|---|---|
| Fixed triggers gone (re-profile) | <list each: gone / still present> |
| New triggers introduced | <none / list> |
| Row reconciliation | <original> − <removed> = <cleaned> <✓/✗> |
| Original unchanged | <✓/✗> |

## RISKS
<What the clean could have got wrong; which assumptions it rests on.>

---
COVERAGE: <rows read>/<total> rows · <sheets> · <files> · strategy: <…> · filters: <…>
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
