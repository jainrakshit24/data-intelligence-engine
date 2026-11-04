# Insight integrity

Load this for EDA and before **any** sentence about aggregated data. It expands core rule 7.

## Contents
- The pre-flight checklist
- Rates and averages: recompute from sums
- Simpson's paradox check
- "Other", "Unknown" and blank
- Small denominators
- Causal language
- Comparisons over time

## The pre-flight checklist

Run through this before writing a finding. Each item that fails is either fixed or stated as a caveat.

- [ ] Every average and rate recomputed as `sum(numerator) / sum(denominator)` over the raw rows.
- [ ] Every percentage carries its base ("of 5,070 orders") and its period ("Jan–Oct 2026").
- [ ] Pooled comparisons checked inside the main segments (Simpson).
- [ ] "Other", "Unknown", blank and placeholder buckets kept out of rankings, with their size stated.
- [ ] Absolute counts shown wherever a denominator is below 30.
- [ ] No causal verb ("drove", "caused", "because of") without a mechanism or an experiment.
- [ ] The finding's coverage is no broader than what was read (rule 6).

## Rates and averages: recompute from sums

**Never average a rate.** The mean of per-region conversion rates is not the overall conversion rate.

```sql
-- wrong: avg(conversion_rate)
SELECT sum(conversions) * 1.0 / NULLIF(sum(visits), 0) AS conversion_rate FROM t;
```

The same applies to pre-aggregated files: if a CSV has a column of daily averages, ask for the counts behind them, or say the pooled figure cannot be computed exactly.

## Simpson's paradox check

Before saying "A is better than B", check the comparison inside each major segment:

```sql
SELECT segment, grp, sum(success) * 1.0 / count(*) AS rate, count(*) AS n
FROM t GROUP BY ALL ORDER BY segment, grp;
```

If the direction reverses inside most segments, the pooled result is driven by **mix** (B has more of an easy segment), not by B. Report both views and say which question each answers.

## "Other", "Unknown" and blank

- Never rank "Other" or "Unknown" as a winner. In the test fixture, `region = 'Other'` is the single biggest bucket (1,714 of 5,070 rows) — "Other is our top region" is not an insight.
- State their size: "34% of orders have no specific region; the ranking below covers the remaining 66%."
- Placeholders (`N/A`) belong here too, not inside a real category.

## Small denominators

- Below 30 in a denominator, show the counts: "2 of 3 (67%)", not "67%".
- Never rank groups where some have fewer than 30 rows without saying so; small groups produce extreme rates by chance.
- Below 5, suppress the group in anything shared outside the team (`privacy-and-pii.md`).

## Causal language

| Write | Only when |
|---|---|
| "is associated with", "coincides with", "is consistent with" | Any observed pattern |
| "likely contributes to" | A plausible mechanism and the data fits it; graded HYPOTHESIS |
| "caused", "drove", "because of" | An experiment, or a mechanism confirmed by a direct check; graded CONFIRMED |

## Comparisons over time

- Compare **like periods**: same weekday mix, same number of days, same timezone. A month with 5 weekends is not comparable to one with 4 without saying so.
- Check that the last period is **complete**. A partial current month always looks like a drop.
- Check that the definition did not change in between (new status values, new source). Look for `correlated-missingness` in the profile.
