# Data context: <project or dataset family>

> Read first on every request (SKILL.md, "First moves"). Only confirmed facts go here.
> Last updated: <YYYY-MM-DD> by <who confirmed>.

## Datasets
| Dataset | Location | Grain (one row =) | Key | Owner |
|---|---|---|---|---|
| <name> | `<path / table>` | <…> | `<col>` | <team> |

## Column meanings
| Dataset.column | Meaning | Unit / currency | Notes |
|---|---|---|---|
| <ds.col> | <…> | <…> | <…> |

## Missing-value markers
<Which strings mean "missing" for which source, e.g. `N/A` and `null` in orders.amount.>

## Date formats
| Dataset.column | Format | Timezone |
|---|---|---|
| <ds.col> | `%Y-%m-%d` | <IST / UTC> |

## Business rules
<Paste-ready for quality_checks.py --rules.>

```json
{
  "required": [],
  "unique": [],
  "ranges": {},
  "allowed": {},
  "freshness": {"column": "<col>", "max_age_hours": 24},
  "volume": {"min_rows": 0, "max_rows": 0}
}
```

## Standing approvals
<Changes the skill may make without asking, e.g. "trim whitespace in text columns". Anything not listed needs approval.>

## Known, accepted issues
<e.g. "legacy_flag is deprecated — ignore it".>

## UNCONFIRMED
<Things believed but not confirmed. The skill treats these as hypotheses.>
