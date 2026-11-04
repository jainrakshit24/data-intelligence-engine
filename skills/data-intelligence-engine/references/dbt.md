# dbt

Load this for DBT_DESIGN (and ELT designs that use dbt). Version notes refer to dbt Core 1.8+; check the user's version (`dbt --version`) before relying on newer features.

## Contents
- Before adding a model
- Project structure
- Materialisations
- Incremental models
- Tests and contracts
- Sources and freshness
- Snapshots (SCD2)
- Running and reviewing

## Before adding a model

- **Extend before adding.** Can an existing model answer this with a column or a filter? A new model is a new thing to test, document and keep in sync.
- **Incremental only when justified.** Under roughly 10M rows, or when a full rebuild takes minutes, a plain `table` is simpler and never drifts. Build it as a full refresh first; switch to incremental only when the full build is measured to be too slow or costly.
- **`unique_key` must be unique in both places**: in the model's output *and* in the target table. Check both (`detect_duplicates.py` on an export, or a `count(*)` vs `count(DISTINCT key)` query) before trusting merge behaviour.

## Project structure

```
models/
  staging/<source>/stg_<source>__<entity>.sql   1:1 with source tables: rename, cast, dedupe. Views.
  intermediate/int_<entity>_<verb>.sql          joins and business logic. Ephemeral or views.
  marts/<domain>/fct_<process>.sql, dim_<entity>.sql   consumer-facing. Tables or incremental.
```

- Every model selects from `{{ ref() }}` or `{{ source() }}`, never a hard-coded table.
- Staging models are the only place that touches sources.
- Each model's YAML states its **grain** in the description.

## Materialisations

| Materialisation | Use when |
|---|---|
| view | Staging; cheap logic; always fresh |
| table | Marts that are queried often and rebuild quickly |
| incremental | Large tables where a full rebuild is too slow or costly |
| ephemeral | Small intermediate logic used once (inlined as a CTE) |
| materialized_view / dynamic table | Platform-managed refresh, where supported |

## Incremental models

```sql
{{ config(materialized='incremental', unique_key='order_id',
          incremental_strategy='merge', on_schema_change='append_new_columns') }}
select order_id, customer_id, amount, updated_at
from {{ ref('stg_shop__orders') }}
{% if is_incremental() %}
  where updated_at >= (select max(updated_at) from {{ this }}) - interval '2 hours'
{% endif %}
```

- `unique_key` + `merge` (or `delete+insert`) makes reruns idempotent; plain `append` duplicates on rerun.
- `insert_overwrite` replaces whole partitions (BigQuery, Spark/Databricks) — good when late data lands in recent partitions.
- `microbatch` (dbt 1.9+) processes by event-time batches and supports targeted backfills. It needs `event_time`, `begin` and `batch_size` on the model (dbt refuses to parse it without `begin`), and `event_time` on every `ref`/`source` it reads, or each batch reads the whole input:
  ```sql
  {{ config(materialized='incremental', incremental_strategy='microbatch',
            event_time='order_ts', begin='2024-01-01', batch_size='day') }}
  ```
- Use a lookback and `>=` (`incremental-loads.md`); `>` on max(updated_at) skips ties.
- `on_schema_change`: `ignore` (default) silently drops new columns from the target — choose `append_new_columns` or `fail` deliberately.
- Plan a `--full-refresh` path and reconcile it against the incremental result once (`reconcile.py`).

## Tests and contracts

```yaml
models:
  - name: fct_orders
    description: One row per order.
    config:
      contract: {enforced: true}       # column names/types checked at build time
    columns:
      - name: order_id
        data_type: varchar
        data_tests: [unique, not_null]
      - name: customer_id
        data_type: varchar
        data_tests:
          - relationships:
              arguments: {to: ref('dim_customer'), field: customer_id}
      - name: status
        data_type: varchar
        data_tests:
          - accepted_values:
              arguments: {values: ['Paid', 'Refunded', 'Pending']}
```

- Minimum per model: `unique` + `not_null` on the grain key. Add `relationships` for every foreign key, `accepted_values` for enums.
- `data_tests:` is the key name from dbt 1.8 (older projects use `tests:`). From dbt 1.10, test arguments go under `arguments:` as above; the old top-level form still runs but raises `MissingArgumentsPropertyInGenericTestDeprecation` (checked with dbt-core 1.12, `dbt_check.py` DB12). On dbt 1.9 or older, write the arguments at the top level instead.
- Unit tests (dbt 1.8+) check SQL logic on fixed inputs — use them for tricky CASE/window logic.
- Set `severity: warn` only with a reason; a failing grain test must stop the build.
- Translate confirmed rules from `data-context.md` into tests; `quality_checks.py` rules and dbt tests should agree.

## Sources and freshness

```yaml
sources:
  - name: shop
    loaded_at_field: _loaded_at
    freshness: {warn_after: {count: 6, period: hour}, error_after: {count: 24, period: hour}}
    tables: [{name: orders}]
```

Run `dbt source freshness` before `dbt build` in production; a stale source should stop the run.

## Snapshots (SCD2)

Use snapshots to keep history of mutable source rows: `strategy: timestamp` with a reliable `updated_at`, else `strategy: check` on listed columns. Set `invalidate_hard_deletes` (or `hard_deletes`, 1.9+) if deletes must close records. Snapshot from sources/staging, before business logic.

## Running and reviewing

Static review first — works without dbt or a warehouse:

```bash
python3 scripts/dbt_check.py path/to/project --dialect snowflake
```

| Rule | Severity | Finds |
|---|---|---|
| DB04 | high | incremental model without `is_incremental()` (microbatch excepted) |
| DB02 | warn | model with no uniqueness test — grain never checked |
| DB03 | warn | hard-coded relation instead of `ref()`/`source()` |
| DB05 | warn | incremental without `unique_key` (not insert_overwrite/microbatch) |
| DB07 | warn | incremental filter `>` against the target's max |
| DB08 | warn | `ref`/`source` that the project does not define |
| DB13 | high | microbatch model without `event_time`, `begin` or `batch_size` (dbt will not parse it) |
| DB14 | warn | microbatch input (`ref`/`source`) without `event_time`: no per-batch filtering |
| DB15 | high | a package macro or test (`dbt_utils.…`) with no `packages.yml`/`dependencies.yml` installing it: `dbt parse` passes, `dbt compile`/`build` fail |
| DB01, DB06, DB09, DB11, DB12 | info | undocumented model, `on_schema_change` unset, source without freshness, YAML for a missing model, test arguments not under `arguments:` |
| SQxx | — | `sql_check.py` rules on the model SQL (import CTEs `select * from ref()` are not flagged) |

It does not check selected columns against what the upstream model outputs (a column that does not exist fails only at build); read the SQL for that, or compile and run `sql_check.py` on the compiled models. Jinja is rendered minimally, so heavy macro use can leave a model unanalysed (DB00) — then compile and check the output:

- `dbt build` (run + test in DAG order); `--select state:modified+ --defer --state <prod artifacts>` for CI (slim CI).
- Review generated SQL in `target/compiled/` with `scripts/sql_check.py --dialect <warehouse>`.
- Code you wrote but did not compile or run is NOT_VERIFIED; say so. `dbt parse` / `dbt compile` move it to "compiles"; `dbt build` on a dev target moves it to "runs".
