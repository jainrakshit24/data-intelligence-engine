# ML readiness report: <dataset> → <target>

## SUMMARY
`VERDICT (data side): <NOT READY | READY AFTER CHECKS | READY WITH CAVEATS | READY>`
<One sentence: the most important blocker or check, with its number.>

## PREDICTION CONTRACT
| Term | Value | Source |
|---|---|---|
| Prediction moment | <column or rule> | <user / data / assumed> |
| Target and horizon | | |
| Label availability | | |
| Feature cut-off | | |

## TARGET
- Kind: <binary / multiclass / regression>; labelled <n>, unlabelled <n> (excluded)
- Classes: <value n (share)> · …
- Label by month: <lowest month rate → highest month rate>

## LEAKAGE
| Column | Signal | Number | Question for the data owner | Status |
|---|---|---|---|---|
| | separates alone / missingness / dated after / name | <AUC, gap, n of N rows> | | SUSPECTED / CONFIRMED / CLEARED |

## SPLITS
| Check | Result |
|---|---|
| Time order | <evaluation rows older than newest training row> |
| Groups | <shared groups, evaluation rows> |
| Duplicates / conflicting labels | <n> / <n> |

## RECOMMENDATION
1. <Drop / confirm / re-split: ordered, each with its reason>
2. Split: <time-based with a gap of …, grouped by …, stratified>
3. Metric: <PR-AUC / recall at precision … / MAE> because <imbalance, cost>

## NOT CHECKED
<Each flag that was not given, and the check it would have run.>

## SCOPE
Model training is outside this skill. The data is <verdict>; the next step is <…>.

---
COVERAGE: <rows read>/<total> rows · <files> · strategy: <…> · filters: <unlabelled rows excluded, …>
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
