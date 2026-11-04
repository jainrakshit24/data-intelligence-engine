# Data quality

Load this for DATA_QUALITY and GENERAL_DATA_INVESTIGATION. Scoring is in `health-scoring.md`; the workflow is `workflows/assess-data-health.md`.

## Contents
- The six dimensions
- Inferred checks vs user rules
- Writing rules.json
- Reading the output
- NOT EVALUATED and RULE PROBLEMS
- From failing check to finding

## The six dimensions

| Dimension | Question | Checks the script runs |
|---|---|---|
| Completeness | Is the value there? | Not null, not blank, not a placeholder — per `required` column, or every column if none given |
| Validity | Is it an allowed value? | Parses as number/date; event time not in the future; user `ranges`, `allowed`, `patterns` |
| Uniqueness | Is each thing recorded once? | No exact duplicate rows; user `unique` columns and inferred key candidates |
| Consistency | Does it agree with itself? | One spelling per category; one date format; user `expressions` across columns |
| Timeliness | Is it fresh enough? | Only with a `freshness` rule |
| Volume | Is the amount plausible? | Only with a `volume` rule |

Timeliness and volume **cannot be inferred** from a single file. Without a rule they are NOT_VERIFIED and excluded from the score — say so rather than letting a reader assume they passed.

## Inferred checks vs user rules

Every check prints its source:
- `[user]` — from `rules.json`. A confirmed business rule.
- `[inferred]` — proposed by the profile. **A suggestion, not a rule.** "order_id looks like a key" is inferred; it becomes a rule only when the user confirms it.

A report built only on inferred checks says so in its headline caveat. Offer to turn the confirmed ones into `rules.json`, and to save them in `data-context.md`.

## Writing rules.json

```json
{
  "required": ["order_id", "customer_id", "amount", "order_date"],
  "unique": ["order_id"],
  "ranges": {"amount": {"min": 0, "max": 100000}},
  "allowed": {"status": ["Paid", "Refunded", "Pending"]},
  "patterns": {"email": "^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$"},
  "expressions": [{"name": "ship_not_before_order",
                   "sql": "TRY_CAST(ship_date AS DATE) >= TRY_CAST(order_date AS DATE)"}],
  "freshness": {"column": "updated_at", "max_age_hours": 24},
  "volume": {"min_rows": 4000, "max_rows": 6000},
  "weights": {"completeness": 0.3},
  "floor": 50,
  "placeholders_are_missing": true
}
```

- Every key is optional.
- `allowed` is an exact, case-sensitive match. `' Paid'` fails it — that is the point.
- `ranges` work on text columns that hold numbers: the same currency/separator stripping as the profiler is applied.
- `expressions` are a single SQL boolean over the row. Statement separators, comments, and any function that touches files or the database (`read_csv`, `copy`, `attach`, `install`, …) are **rejected**, not run. They are listed under RULE PROBLEMS.
- A rule naming a column that does not exist is listed under RULE PROBLEMS, not silently ignored.

Run:

```bash
python3 scripts/quality_checks.py <path> --rules rules.json [--json]
```

## Reading the output

With rules (test fixture `orders.csv`):

```
DATA HEALTH SCORE: 83.0/100  —  CRITICAL  (6 of 6 dimensions measured)
  CRITICAL because timeliness < floor 50 (an average must not hide a broken dimension)
```

Without rules, the same file:

```
DATA HEALTH SCORE: 94.5/100  —  PROVISIONAL  (4 of 6 dimensions measured)
  PROVISIONAL because every check is inferred — no business rule confirmed (band would be: production-ready). Pass --rules to certify.
  checks below 50% hidden inside the averages: legacy_flag not missing 8.0%
```

- The headline always says how many dimensions were measured. "100/100 (3 of 6)" is not a clean bill of health.
- **PROVISIONAL** means no check came from the user. The 94.5 above is lifted by 17 mostly-complete columns, while 70 order_ids repeat and 30% of `quantity` does not parse. Never report a provisional score as "ready".
- "checks below 50% hidden inside the averages" names single checks that a dimension mean would bury. Mention each one.
- `✗` marks every check below 99.9%. `failing/evaluated` gives the exact counts.

## NOT EVALUATED and RULE PROBLEMS

- **NOT EVALUATED** lists user rules that could not judge every row: the value was missing, or the rule could not parse it. Example: `TRY_CAST(order_date AS DATE)` returns NULL for `31/10/2026`, so 14% of rows were never checked by the ship-date rule. **Its pass rate covers fewer rows than it appears to.** Report the skipped share next to the pass rate, and fix the rule (parse the right format) rather than ignoring it.
- **RULE PROBLEMS** lists rules that did not run at all. Each one is a gap in the report.

## From failing check to finding

A failing check is an OBSERVATION. Turn it into a finding with the evidence ladder:

```
FINDING:     17 orders ship before they were ordered (ship_not_before_order: 17 failing / 4,353 evaluated).
EVIDENCE:    quality_checks.py, user rule; 717 rows not evaluated (day-first dates).
MEANING:     HYPOTHESIS — a date-format mix-up or a data-entry error.
CONFIDENCE:  Medium — 14% of rows were not evaluated.
NEXT CHECK:  Re-run with both dates parsed by their real formats.
```

Then point at the fix: cleaning (`data-cleaning.md`) for value-level problems; the source system or pipeline (Phase 3 module, not yet built — give general guidance) for anything systematic.
