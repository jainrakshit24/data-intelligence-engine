# Playbook: volume

Row counts moved: a day is down 30%, a partition is empty, a table doubled. Shared method: `../root-cause-investigation.md`.

## Measure
1. `anomaly_detection.py <table> --time <event_time> --by <segment>`: when it started, how big, and which segments moved. Try 2–3 segment columns (source system, region, channel, event type). The one where a single value explains most of the change is the lead.
2. `reconcile.py <source> <target> --key <key>` for the hop where counts diverge. It splits the difference into dropped keys, new keys, collapsed duplicates, fan-out and null keys, exactly.

## Hypotheses and the check that separates them

| Hypothesis | Check | Supports it |
|---|---|---|
| Real business change | Other sources (orders vs payments, web analytics); calendar | The drop appears independently in a system the pipeline does not touch |
| Source sent less | Source-side count for the same window | Source is down by the same amount |
| A filter started removing rows | `reconcile.py` dropped keys; new or changed `WHERE` in the code diff | Dropped keys share a value (a status, a null in the filter column) |
| A join lost rows | `reconcile.py`: dropped rows concentrated where the join key is null or unmatched | `INNER JOIN` to a dimension that lacks the new keys |
| A join fanned out | `reconcile.py` "fanned out" > 0; `sql_check.py --grain` | Keys appear more often in the output than the input |
| Duplicates collapsed or appeared | `detect_duplicates.py --key` on both sides | Change equals duplicate count |
| Partial load | Rows per file or partition; job logs | One file or partition is missing or short |
| A segment disappeared | `--by` split: one segment → 0 | That segment's feed, mapping or permission changed |

## Usual fixes
- Restore the missing feed or mapping, then backfill the affected periods and verify each with `reconcile.py` (delta = 0, or fully explained).
- For fan-out: fix the join to the right grain (an `is_current` filter on an SCD2 dimension, a dedupe before the join), then prove it with `sql_check.py --grain`.

## Prevention

```bash
python3 scripts/anomaly_detection.py orders.parquet --time order_ts --by source_system \
    --complete-through "$(date -d yesterday +%F)" --fail-on-anomaly
```
plus a `volume` rule in the contract for hard limits.
