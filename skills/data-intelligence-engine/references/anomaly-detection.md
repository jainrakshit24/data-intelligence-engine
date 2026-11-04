# Anomaly detection

Load this for ANOMALY_DETECTION, and for PIPELINE_DEBUGGING when the symptom is "the numbers look wrong". It covers finding anomalies over time; explaining them is `root-cause-investigation.md`. The workflow is `workflows/investigate-anomaly.md`.

## Contents
- What counts as an anomaly
- Running the scanner
- How it decides
- Reading the output
- Traps that make false anomalies
- Monitoring setup
- What the scanner cannot see

## What counts as an anomaly

An anomaly is a value that the data's own history says is unlikely. It is an **OBSERVATION** (rule 1). "Orders dropped 25% on 6 April" is an observation. "The CRM sync broke" is a hypothesis until a check supports it.

| Kind | Looks like | Series to scan |
|---|---|---|
| Volume | Fewer or more rows than usual; an empty day | row count per period |
| Level shift | A step change that persists ("30% fewer since Tuesday") | row count, metric mean |
| Metric | A mean or total far outside its range (unit bug, double count) | `--metric` mean |
| Missingness | A column suddenly blank for many rows | `--nulls` missing share |
| Freshness | The newest period is missing or partial | last period, `--complete-through` |

A shift in a *whole distribution* between two snapshots is drift, not an anomaly over time: `data-drift.md`.

## Running the scanner

```bash
python3 scripts/anomaly_detection.py events.csv --time event_time \
    --metric amount --nulls coupon,customer_id --by region
```

| Flag | Use |
|---|---|
| `--time` | The event-time column. It must be when the thing happened, not when it was loaded, unless load delay is the question |
| `--grain` | `day` by default. `hour` for intraday feeds; `week`/`month` for sparse data. Hour grain adjusts hour-of-day only, not weekday, so a quiet weekend just before a step can pull its date earlier: date a level shift at day grain |
| `--metric` | Numeric columns whose **mean** per period is scanned |
| `--nulls` | Columns whose missing share (null, blank, placeholder) per period is scanned |
| `--by` | One segment column. Each shift and each row-count anomaly is split into the segments that moved. Shares sum to 100%; one segment can exceed 100% when others moved the other way |
| `--complete-through` | Last date whose data is complete. Later periods are reported as incomplete, not scored |
| `--seasonal none` | Turn off the weekday / hour-of-day adjustment (for comparison only) |
| `--fail-on-anomaly` | Exit 1 if anything is flagged, for schedulers |

It prints only per-period aggregates. With `--by` on a column whose name looks personal, segment values are masked.

## How it decides

1. **Buckets.** Rows are grouped by period. Empty periods are kept as 0 and always listed: an empty day is never "smoothed away".
2. **Seasonality.** At day grain, each weekday gets a factor (median of that weekday ÷ overall median), and the same for hour-of-day at hour grain. It needs 3+ values per slot. Row counts are divided by their factor, so a quiet Sunday is not a drop.
3. **Level shift.** The strongest single step in the series (more than 5 periods on each side; a step only 1–5 periods old is not dated yet, and its periods show up as point anomalies instead). Noise is measured from period-to-period differences, so the step does not hide itself. It is reported when t ≥ 6 and the change is ≥ 5%; before/after are medians.
4. **Points.** Robust z = (value − level) ÷ sigma. The level is the median of the point's side of the shift. Sigma is 1.4826 × MAD of the residuals, never below the period's own sampling noise (√expected for counts, binomial SE for rates, sd/√n for means). |z| > 3.5 is flagged (Iglewicz–Hoaglin).
5. **Small periods.** Means and rates are not scored below 30 rows (rule 7).

Why robust statistics: a mean and standard deviation are pulled by the very outliers you are looking for. A single 10× day inflates the sd until nothing looks unusual. Median and MAD ignore it.

## Reading the output

```
LEVEL SHIFTS
  rows   196 → 146 per period (seasonally adjusted) (-25.3%) from 2026-04-06   t=43.4
    North    43.8 →  0.0   -43.8   94% of the change
POINT ANOMALIES
  2026-02-11  rows                361  expected ~201   z +11.3  spike
      East     212 vs ~51  +161  100%
  2026-03-18  mean(amount)  51,758.26  expected ~550.41  z +30.2  spike
```

- **Report the absolute numbers**, not just z: "361 rows against ~201 expected" is checkable; "z = 11" is not.
- **Segment shares** say where the change sits, not why. "94% of the drop is North" narrows the search. It does not prove the North feed broke.
- **A ×10, ×100 or ×1000 metric spike** is the signature of a unit change (paise vs rupees, cents vs dollars, ms vs s). Confirm with the raw values' magnitude before calling it that.
- **"low, but the last period may be incomplete"** means just that. Without `--complete-through` the scanner cannot tell a partial day from a real drop. Ask, or check the load time.

## Traps that make false anomalies

| Trap | Symptom | Guard |
|---|---|---|
| Incomplete last period | Today is "down 60%" | `--complete-through`; check the max timestamp against now |
| Load time instead of event time | Spikes on backfill days | Scan the event-time column; scan load time separately if lag is the question |
| Calendar effects | Holidays, month-end, sale days flagged | Confirm against a calendar before calling it a defect; say "consistent with <holiday>" |
| Mixed time zones | Day boundaries shift; a ±1-day echo of every spike | Check the column's zone (`references/data-cleaning.md`, dates) |
| Late-arriving data | Recent days low, then "recover" on re-run | Re-scan after the lookback window; compare runs |
| Denominator shift | A rate moves because the population moved | Scan the count too; split with `--by` |
| Many series | At 3.5, normal noise alone crosses about once per 2,000 periods per series; heavy-tailed data more often | Weigh a lone borderline z (3.5–5) lower than a large or repeated one |

## Monitoring setup

For "alert me when this breaks", hand the user a scheduled command; the skill does not run the schedule (rule 2):

```bash
python3 scripts/anomaly_detection.py "export/orders_*.parquet" --time order_ts \
    --complete-through "$(date -d yesterday +%F)" --nulls customer_id --fail-on-anomaly --json \
  > anomaly.json || notify "orders anomaly: see anomaly.json"
```

Pair it with `quality_checks.py --rules contract.json --fail-on-violation` for the rules that must always hold (`data-contracts.md`). The monitor that would have caught an incident is the **Prevention** section of every root-cause report.

## What the scanner cannot see

- **Anomalies inside a single period's rows** (one bad record among thousands): that is data quality, `data-quality.md`.
- **Several shifts at once.** It reports the strongest one. After explaining it, re-scan the window after the shift.
- **Seasonality longer than a week** (monthly, yearly). Compare against the same period last year by hand, and say the scan did not adjust for it.
- **Causes.** Every finding goes to `root-cause-investigation.md` before it is called a cause.
