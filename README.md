# Data Intelligence Engine

An Agent Skill that takes a data problem and works out what to do with it.

You bring a dataset, a pipeline, a SQL file or just a question. It classifies the request, loads
only the methodology that request needs, runs the checks, and reports what it found — with every
claim graded by the evidence behind it.

It is not a menu of commands. You describe the problem in your own words.

```
> this orders.csv came from the new export, is it any good?

DATASET  orders.csv  (csv, 758 KiB)  rows 5,070  columns 17
DATA HEALTH SCORE: 94.5/100  —  PROVISIONAL  (4 of 6 dimensions measured)

RISK TRIGGERS  (14)
  [duplicate-key]  order_id: looks like a key but 70 rows repeat an existing value
  [mixed-date-formats]  order_date: %Y-%m-%d 85.9%, %d/%m/%Y 14.1%
  [silent-nulls]  amount: 120 placeholder values ('n/a'×100, 'null'×20) = 2.4% of rows
  [polluted-type]  quantity: only 70.1% of present values parse as numbers
  …

COVERAGE: 5,070/5,070 rows · 1/1 files · strategy: whole · filters: none
```

That score says `PROVISIONAL` because every check was inferred rather than confirmed against
your business rules. The skill will not quietly drop the word.

## Install

```bash
git clone https://github.com/jainrakshit24/data-intelligence-engine
cd data-intelligence-engine
pip install -r code/requirements.txt
ln -s "$PWD/code" ~/.claude/skills/data-intelligence-engine
```

Restart your agent. It picks the skill up by name and uses it when a request fits — you do not
invoke it by hand.

The methodology works without the Python packages. The scripts do not, and the skill says which
one could not run rather than guessing around it.

## What it handles

| You have | It does |
|---|---|
| A CSV, TSV, Parquet, JSON, Excel file or a database table | Profiles it, scores its health, surfaces the risks worth knowing about |
| Data that changed and you don't know why | Finds volume, metric and null-rate anomalies, level shifts, and the segments that moved |
| Two versions of a dataset | Reconciles them row by row and unit by unit |
| A pipeline, dbt project, Airflow DAG or SQL file | Reviews it statically — without running it, importing it, or needing the tool installed |
| A dataset headed for a model | Checks it for leakage, class balance and split problems. The data side only |
| Definitions nobody wrote down | Records them as a `data-context.md` it reads first next time |

Twenty-seven intents in all, and a request routes to as many as apply: *"my daily customer
pipeline has 30% fewer records, find out why"* is a quality check, an anomaly scan, a pipeline
debug and an investigation at once.

## The rules it will not bend

Seven rules apply to every request. These four are why the reports can be trusted:

**Profile, don't read.** The scripts compute; the model sees only aggregates. Opening a data
file into an agent's context sends its rows to the model provider, so this skill does not do it
— and says so when something else does.

**No fake execution.** A check that could not run is reported `NOT_VERIFIED` and is never
promoted to a finding. "I could not reach the database" is an answer; a guess dressed as one is
not.

**Coverage, in numbers.** Every report states how much data it actually covered. No claim may be
broader than its coverage, and a sample produces an estimate, labelled as one.

**Data is never instructions.** Text inside a cell that reads like a command is data. If it
looks like an injection attempt, that is itself a finding — and the fixtures include four.

The other three: an evidence ladder that keeps OBSERVATION, INTERPRETATION, HYPOTHESIS and
CONFIRMED apart; no silent changes to your data; and arithmetic integrity, so averages are
recomputed from sums and counts and a pooled comparison is checked for reversal inside the
groups.

## The scripts

Eleven of them, in `code/scripts/`. The skill runs them for you; you can also run them directly.

| Script | What it answers |
|---|---|
| `profile_dataset.py` | What is in this file, and what should worry me? |
| `quality_checks.py` | Does it pass its rules, and what is its health score? |
| `detect_duplicates.py` | Are there duplicate rows, or duplicate business keys? |
| `dataset_summary.py` | One screen, for a first look |
| `anomaly_detection.py` | What changed over time, and in which segment? |
| `drift_check.py` | What moved between two snapshots — schema or distribution? |
| `reconcile.py` | Did every row and every unit survive the pipeline? |
| `ml_readiness.py` | Is this dataset leaking, imbalanced, or badly split? |
| `sql_check.py` | What does this SQL read, write and break? |
| `dag_check.py` | What is wrong with this Airflow DAG, without importing it? |
| `dbt_check.py` | What is wrong with this dbt project, without running it? |

Every one of them prints aggregates and a `COVERAGE:` line, and none prints raw rows by default.

## How it is put together

```
code/
├── SKILL.md       the router — the only file loaded every time
├── references/    32 methodology modules, loaded only when an intent names one
├── workflows/     11 step-by-step procedures
├── templates/     9 report shapes
├── scripts/       the 11 scripts above
└── requirements.txt
```

**Progressive disclosure is the point.** `SKILL.md` is a thin router; the other 52 modules load
only when an intent names them. A typical task reads a fraction of the corpus, so the
methodology can be thorough without every request paying for all of it.

## Out of scope, on purpose

It does not train, tune, evaluate or deploy models. Asked to "build a model", it checks the data
is ready and then says where its job ends.

It has no live connectors to warehouses or BI tools. It writes the SQL, labels it
`NOT_VERIFIED`, and asks you to run it.

Both limits are deliberate: a skill that pretends to have run something is worse than one that
tells you it did not.

## Requirements

Python 3.9+, `duckdb>=1.1`, `sqlglot>=30` for SQL work, and `pyyaml` for dbt projects.

## Licence

MIT.
