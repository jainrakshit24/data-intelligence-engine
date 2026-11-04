# Data contracts

Load this for DATA_CONTRACT. A data contract is an agreement between the team that produces a dataset and the teams that consume it: what the data looks like, what rules it always meets, how fresh it is, who owns it, and how it may change. This module writes contracts and checks data against them. How to change a contracted schema safely is `schema-evolution.md`.

## Contents
- What goes in a contract
- The contract file this skill checks
- Checking data against a contract
- Where to enforce it
- From an existing dataset to a first contract
- Contracts in dbt and other tools
- What a contract cannot promise

## What goes in a contract

| Section | Holds | Example |
|---|---|---|
| Identity | Dataset name, owner (a team, not a person), consumers | `orders_daily`, owner: payments-data |
| Schema | Every column: name, type, nullable, meaning | `amount: number, required, rupees incl. tax` |
| Grain and keys | What one row is; the unique key | one row per order; `order_id` unique |
| Rules | Allowed values, ranges, cross-column rules | `status in (Paid, Refunded, Pending)` |
| Service level | Freshness, delivery time, volume range | complete by 06:00 IST; 4k–6k rows/day |
| Change policy | How changes are announced and versioned | additive: 7 days' notice; breaking: new version + 30-day overlap |
| Personal data | Which columns are personal, their purpose and retention | `email`: direct identifier, support use only |

Units belong in the schema. "amount" without "rupees, paise or dollars" is how unit-change incidents start (`root-cause/field-drift.md`).

## The contract file this skill checks

The machine-checkable part of a contract is a `quality_checks.py` rules file with a `schema` section:

```json
{
  "schema": {"order_id": "string", "customer_id": "string", "amount": "number",
             "quantity": "integer", "order_date": "date", "status": "string"},
  "schema_strict": true,
  "required": ["order_id", "customer_id", "amount", "order_date"],
  "unique": ["order_id"],
  "allowed": {"status": ["Paid", "Refunded", "Pending"]},
  "ranges": {"amount": {"min": 0, "max": 100000}, "quantity": {"min": 1}},
  "expressions": [{"name": "ship_not_before_order",
                   "sql": "TRY_CAST(ship_date AS DATE) >= TRY_CAST(order_date AS DATE)"}],
  "freshness": {"column": "updated_at", "max_age_hours": 24},
  "volume": {"min_rows": 4000, "max_rows": 6000}
}
```

| Key | Checks |
|---|---|
| `schema` | Each column exists, and each non-missing value casts **strictly** to its type: `integer`, `number`, `date`, `timestamp`, `boolean`, `string`. `1,234`, `₹50` and `02/01/2026` fail: a contract number is a plain number, a contract date is ISO |
| `schema_strict` | `true`: a column the schema does not declare fails ("declared in schema") |
| everything else | As in `data-quality.md` |

Identity, change policy and personal-data purpose do not fit a rules file. Keep them in the contract document (`templates/data-context.md` has room for definitions, or the team's own contract format), next to the rules file.

## Checking data against a contract

```bash
python3 scripts/quality_checks.py today.csv --rules contract.json --fail-on-violation
```

- Exit 0: every rule from the contract passed. Exit 1: at least one failed. Inferred checks never trip the gate; only the contract's terms do.
- A violation is reported as the check, the column and the failing row count, never the failing values.
- A contract that names a column the data lacks fails "column present (schema)". It is not silently skipped.
- An unknown type in `schema` is listed under RULE PROBLEMS: the contract itself is broken.

For "what changed since the contract was written", run `drift_check.py` between a snapshot that met the contract and today's data.

## Where to enforce it

| Point | How | Stops |
|---|---|---|
| Producer CI | Run the check on a sample output before merging producer code | Breaking changes before they ship |
| Before load (landing zone) | `--fail-on-violation`; on failure, quarantine the file and alert | Bad files reaching the warehouse |
| After transform | dbt contract + tests, or the same rules file on the model output | Pipeline logic breaking the terms |
| Monitoring | Scheduled check plus `anomaly_detection.py` | Slow decay that no single run fails |

Enforce **before** consumers read the data. A check after the dashboard refreshed is a post-mortem, not a contract.

## From an existing dataset to a first contract

1. `profile_dataset.py` the dataset. Types, missing shares and key candidates are the draft.
2. Turn inferred facts into **proposed** terms. Everything inferred is a proposal until the owner confirms it (rule 1).
3. Ask the owner only what data cannot answer: units, meaning, freshness promise, change policy, who consumes it.
4. Run `quality_checks.py --rules contract.json` on recent history. A contract today's data already breaks is either wrong or describes a known defect. Say which.
5. Save confirmed definitions in `data-context.md` (`workflows/build-data-context.md`).

## Contracts in dbt and other tools

- **dbt**: `contract: {enforced: true}` with `data_type` per column checks names and types at build time; tests carry the rules (`dbt.md`, "Tests and contracts"). Keep the rules file and the dbt tests in agreement.
- **Open Data Contract Standard (ODCS)** and similar YAML formats hold the full document. Map its schema and quality sections to the rules file above for checking here.
- **Schema registries** (Avro / Protobuf / JSON Schema) enforce schema compatibility on streams. They do not check values, so pair them with rules.

## What a contract cannot promise

- **Correctness of meaning.** Every row can pass and `amount` can still exclude tax when consumers think it includes it. Definitions need words, not only rules.
- **Completeness against reality.** A contract can bound volume; it cannot know which real orders were never sent.
- **Anything nobody checks.** A contract without an enforcement point is documentation.
