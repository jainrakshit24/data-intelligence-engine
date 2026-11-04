# Safe database access

Load this whenever SQL will run against a real database, or the user offers credentials or a connection.

## Contents
- What the skill can and cannot reach
- Credentials
- Read-only by default
- Cost and load
- Aggregates, not rows
- Writes

## What the skill can and cannot reach

The scripts read files. They do not connect to databases. To work with a database:
1. **The user runs the SQL** and shares the aggregate result, or
2. The user exports a table or query result to Parquet/CSV and the scripts analyse the file, or
3. If the environment provides a database tool (an MCP server, a CLI the user has configured), use it under the rules below.

Never claim a result from a database you did not reach (rule 2). "This query should return about…" is a HYPOTHESIS.

## Credentials

- Never ask for a password or token to be pasted into the chat. Point to the engine's own mechanism (environment variables, `~/.pgpass`, a profile file, SSO).
- Never write credentials into SQL, code, `data-context.md` or a report.
- If credentials appear in the conversation or a file, do not repeat them; tell the user to rotate them.

## Read-only by default

- Prefer a read-only role or a read replica. Say which one the user should use.
- **Check read-only by inspecting grants, not by trying a write** (`SHOW GRANTS TO ROLE …` in Snowflake; `has_table_privilege(…, 'INSERT')` in Postgres; IAM roles in BigQuery). A test write on a role that turns out to be writable has already written.
- **Bound before you scan.** Read the plan (`EXPLAIN`) and run a bounded probe (one partition, `LIMIT` on an aggregate, a `TABLESAMPLE`) before any query that could scan everything.
- Set a statement timeout before running anything heavy (`SET statement_timeout = '60s'` in Postgres; `STATEMENT_TIMEOUT_IN_SECONDS` in Snowflake).
- `sql_check.py --fail-on destructive` before running a file you did not write.

## Cost and load

- On metered warehouses, estimate before running: BigQuery `--dry_run` (bytes processed), Snowflake warehouse size × expected time. Tell the user the estimate.
- Filter on partition/cluster columns; avoid `SELECT *` on wide tables.
- Run against production during quiet hours, or against a replica.
- For exploration, `TABLESAMPLE` / a recent partition, labelled as a sample (rule 6).

## Aggregates, not rows

Queries for analysis return aggregates: counts, null counts, `count(DISTINCT)`, min/max of non-identifier columns, grouped counts at a non-identifying grain. The same privacy rules as files apply (`privacy-and-pii.md`):
- no `SELECT * … LIMIT 10` on tables with people in them;
- no group-by on identifier columns;
- small groups (< 5) suppressed.

## Writes

Any INSERT, UPDATE, DELETE, MERGE, DDL or COPY:
1. Show the statement, the target, and the expected rows affected (from a `SELECT count(*)` with the same WHERE).
2. Say how to undo it: a backup table (`CREATE TABLE x_backup_20261102 AS SELECT * FROM x`), time travel (Snowflake `AT`, BigQuery `FOR SYSTEM_TIME AS OF`, Delta/Iceberg versions), or a transaction.
3. Get explicit approval for **this** statement, quoting the expected count. Approval for one write does not cover the next.
4. Run it inside a transaction where the engine supports one, and check the affected count before `COMMIT`.
5. If the count differs from the estimate, roll back and report; otherwise commit and record the count.
