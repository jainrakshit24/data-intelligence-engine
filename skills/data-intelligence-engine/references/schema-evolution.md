# Schema evolution

Load this for SCHEMA_ANALYSIS, and with DATA_CONTRACT or any pipeline change that alters a table's columns. It covers changing a schema without breaking consumers. Detecting a change that already happened is `data-drift.md`; diagnosing the damage is `root-cause/schema-change.md`.

## Contents
- Which changes break whom
- Before changing a schema: change impact
- Safe patterns for each change
- Versioning and deprecation
- In the warehouse and lakehouse
- Checklist

## Which changes break whom

| Change | Readers by column name | `SELECT *` / positional | Strict contract |
|---|---|---|---|
| Add a nullable column | safe | may break | breaks if `schema_strict` |
| Add a required column | safe for readers; **breaks writers** that don't supply it | may break | update contract first |
| Remove a column | **breaks** | breaks | breaks |
| Rename a column | **breaks** (it is a remove + add) | breaks | breaks |
| Widen a type (int → bigint, varchar(50) → varchar(200)) | usually safe | usually safe | update contract |
| Narrow or change a type (text → int, number → text) | **breaks** casts and comparisons | breaks | breaks |
| Change meaning or units, same name and type | **silently wrong** | silently wrong | passes (the worst case) |
| Change the grain (one row per order → per order line) | **silently wrong** sums and counts | same | passes unless the unique key is in the contract |

The last two rows are the dangerous ones: nothing fails, every number moves. Treat them as breaking.

## Before changing a schema: change impact

1. **Find every consumer.** Lineage from `sql_check.py --lineage` over consumer queries, `dbt_check.py` / `ref()` for dbt, BI tool dependencies, exports. List each one with its owner.
2. **Classify the change** with the table above.
3. **Write 3–5 before/after checks** that must hold after the change, for example:
   - `reconcile.py old_version new_version --key order_id --sum amount`: no rows lost, sums equal.
   - `drift_check.py old new`: only the intended columns changed.
   - `quality_checks.py new --rules contract.json --fail-on-violation`.
   - `sql_check.py --grain` on models that join the table.
4. **Decide the path**: additive change, or versioned change with a deprecation window.

## Safe patterns for each change

**Add.** Add as nullable or with a default. Backfill if history needs it. Announce it; consumers opt in.

**Rename.** Expand, migrate, contract:
1. Add the new column and write both, or expose the new name through a view.
2. Move consumers to the new name; confirm with lineage that none still read the old one.
3. Remove the old column after the agreed window.

**Retype.** Add a new column with the new type (`amount_paise BIGINT` beside `amount NUMERIC`), dual-write, migrate, then retire. Never cast in place under consumers.

**Change units or meaning.** New column with the unit in its name. Never reuse the old name for a new meaning.

**Change the grain.** New table. The old one keeps its grain until retired.

**Remove.** Deprecate first (announce, log or monitor reads if the platform allows), then remove after the window.

## Versioning and deprecation

- Additive changes: same version, announced.
- Breaking changes: a new version (`orders_v2`, a new topic, a new contract version), run **both** for an overlap window, then retire the old one on a published date.
- dbt: model versions (`versions:` with `latest_version`) express exactly this; the old version keeps building during the window.
- Record each change in the contract's change log: what, why, date, who approved.

## In the warehouse and lakehouse

- Table formats (Delta, Iceberg, Hudi) support add and rename as metadata operations. A metadata rename is still a breaking change for every consumer by name.
- Iceberg tracks columns by ID, so renames don't rewrite data. Delta needs column mapping enabled for renames and drops.
- Schema-on-read loaders (auto-detect, `union_by_name`) absorb new columns silently and can turn a renamed column into a column of NULLs. Pin the schema in the staging layer.
- Partition-column changes rewrite or re-layout data: plan them as a migration, not a schema tweak.

## Checklist

```
- [ ] Every consumer listed, with owner
- [ ] Change classified (additive / breaking / silently wrong)
- [ ] Before/after checks written and run on a copy
- [ ] Breaking: new version + overlap window + retirement date
- [ ] Contract updated (schema, change log) before the change ships
- [ ] Backfill plan for history, if any
```
