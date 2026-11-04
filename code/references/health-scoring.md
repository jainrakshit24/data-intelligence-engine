# Health scoring

Load this for DATA_QUALITY. It documents exactly what `scripts/quality_checks.py` computes. If the two ever disagree, the script is what ran: report the script's number and raise the mismatch.

## Contents
- The formula
- Default weights
- The critical floor
- Bands
- NOT_VERIFIED dimensions
- Changing weights or the floor
- How to present the score

## The formula

```
check pass rate  = (rows evaluated − rows failing) / rows evaluated      (1.0 if nothing evaluated)
dimension score  = 100 × mean(pass rate of the dimension's checks)
composite        = Σ (weight_d × score_d) / Σ weight_d     over MEASURED dimensions only
```

- Each check counts equally inside its dimension, however many rows it covers.
- Volume and timeliness checks are pass/fail (evaluated = 1).
- Scores are rounded to one decimal.

## Default weights

| Dimension | Weight |
|---|---|
| completeness | 0.20 |
| validity | 0.20 |
| uniqueness | 0.20 |
| consistency | 0.15 |
| timeliness | 0.15 |
| volume | 0.10 |

Because the composite divides by the weights of measured dimensions only, the weights do not need to sum to 1.

## The critical floor

If **any measured dimension scores below the floor (default 50)**, the status is **CRITICAL**, whatever the composite. An average must not hide a broken dimension: data that is 100% complete and 40% unique is not "fine on average".

## Bands

| Composite | Status |
|---|---|
| any dimension < floor | CRITICAL |
| ≥ 85 | production-ready |
| 65 – 84.9 | usable with caveats |
| < 65 | remediate before use |
| nothing measured | NOT_VERIFIED |
| no check came from `--rules` (and not CRITICAL) | **provisional** — the band is reported separately as `band` |

**Provisional.** Inferred checks are proposals, so they cannot certify data. Without `--rules` the status is `provisional` and the headline says what the band *would* be. Test fixture: 94.5 with no rules ("would be production-ready") vs 83.0 CRITICAL once real rules run.

**Weak checks.** Any single check with a pass rate below the floor is listed under the headline ("checks below 50% hidden inside the averages"), because a dimension mean can bury one broken check just as the composite can bury a dimension.

"production-ready" here means *the checks that ran passed*. It is not a guarantee about checks that did not run — always quote the "N of 6 dimensions measured" part with it.

## NOT_VERIFIED dimensions

A dimension with no applicable check is **excluded**, never scored 0 or 100:
- timeliness — no `freshness` rule
- volume — no `volume` rule (one snapshot has no expected range)
- any other — no check applied

List excluded dimensions next to the score.

## Changing weights or the floor

Only on the user's word, or from `data-context.md`. Put them in `rules.json` (`"weights": {...}`, `"floor": 60`), and state the change in the report. Never tune weights to move a score across a band.

## How to present the score

```
DATA HEALTH: 83.0/100 — CRITICAL (6 of 6 dimensions measured)
Why critical: timeliness 0 — latest updated_at is 2026-10-02 21:00, 737 h old against a 24 h rule.
Next weakest: consistency 93.2 — order_date in two formats (717 rows day-first); status in 304 non-canonical spellings.
```

Lead with the weakest dimension and the check behind it. The number alone tells nobody what to fix.
