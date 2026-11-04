# Playbook: field drift

A column's values changed: its null rate, mean, units, category mix or format. Rows and schema may look normal. Shared method: `../root-cause-investigation.md`.

## Measure
- `drift_check.py <before> <after>`: which columns moved, PSI and severity, missing share, unit-change hint, vanished and new categories.
- `anomaly_detection.py --metric <col> --nulls <col> --by <segment>`: the first period it changed and in which segment.

## Hypotheses and the check that separates them

| Hypothesis | Check | Supports it |
|---|---|---|
| Unit or scale change | Median ratio ≈ 10ᵏ (`drift_check.py` hint); source documentation | ×100 from one date, often one source only |
| New category or code from the source | New values and their share; source release notes | A new enum value appears at a clean date |
| Mapping table out of date | Unmapped share before vs after | New source codes map to NULL or "Other" |
| Upstream default changed | The value that grew is a default (0, "Unknown", epoch date) | One value absorbs the share |
| Field stopped being populated | Missing share by segment and source | One source, app version or form stops sending it |
| Real-world shift | An independent source shows the same move; a known event | Change is gradual, or matches a campaign, season or market change |
| Population shift | Drift in who is counted (new region, new channel) | Drift disappears inside each segment |

The last row is Simpson's paradox at the column level (`insight-integrity.md`): check drift **within** segments before blaming the field.

## Usual fixes
- Normalise units or codes in the staging layer, with the conversion stated; restate affected history if consumers compare across the change.
- Update the mapping, then reprocess rows mapped to "Other" since the change date.

## Prevention

```bash
python3 scripts/drift_check.py baseline_month.parquet latest_month.parquet --fail-on major
```
plus `allowed` values and `ranges` in the contract for fields with known domains.
