# Exploratory data analysis (EDA)

Load this for EDA, with `data-profiling.md` and `insight-integrity.md`. The workflow is `workflows/analyze-data.md`.

## Contents
- Start from questions, not charts
- The EDA ladder
- Outliers
- Relationships
- Time
- Turning a pattern into a finding
- Running queries

## Start from questions, not charts

Write 3–5 questions before running anything. If the user gave none, derive them from the data's purpose: *What is one row? What is the outcome column? Who would act on this?* State the questions in the report so the reader can judge whether the analysis answered them.

Prefer three findings that matter over thirty charts.

## The EDA ladder

Climb only as far as the questions need.

1. **Grain.** What is one row? Is the key unique? (`detect_duplicates.py`). Every later number depends on this.
2. **Univariate.** Distribution of each important column: from the profile, not recomputed by hand.
3. **Segments.** The outcome by the 2–3 most important categorical columns, with counts.
4. **Relationships.** Two numeric columns together; an outcome against a driver.
5. **Time.** Trend, seasonality, breaks.

## Outliers

An outlier is an OBSERVATION. Before calling it an error:
- Find how many there are and their share of the total (one order can be 30% of revenue).
- Check whether it matches a known pattern: bulk orders, test accounts, a currency mix-up (×100), a unit change.
- Report results **with and without** them when they move a conclusion.

Say which rule you used:
- Roughly symmetric data: the IQR rule (`< p25 − 1.5·IQR` or `> p75 + 1.5·IQR`).
- Right-skewed data (amounts, durations, counts — mean well above median in the profile): the IQR rule on raw values flags much of the normal upper tail. Apply it to `log(value)` for positive values, or report the top percentiles (p99, p99.9) and the share of the total they hold.
- Never use mean ± 3·std on skewed data: the outliers inflate the std that is meant to find them.

## Relationships

- Correlation coefficient: state the method (Pearson for linear, Spearman for monotonic/skewed) and the n.
- A correlation over pooled groups can come from the grouping alone — run the Simpson check.
- Never infer direction from correlation.

## Time

- Aggregate by a calendar unit that matches the question, and in the business's timezone.
- Mark incomplete periods (the current day/month).
- A step change is a finding to explain: look for a new source, a definition change, a deploy, or `correlated-missingness`.

## Turning a pattern into a finding

Each finding has five parts. If you cannot fill EVIDENCE with a number and its base, it is not a finding yet.

```
FINDING:     Refunds are 20.0% of order rows (1,013 of 5,070), records updated Jan 2025 – Oct 2026.
EVIDENCE:    status counted after lower(trim()) (query below); exact "Refunded" alone gives 960.
MEANING:     INTERPRETATION — high for retail; may include partial refunds.
CONFIDENCE:  Medium — 304 status values were case/whitespace variants and were mapped,
             and 70 rows repeat an order_id, so the base is rows, not unique orders.
NEXT CHECK:  Refund rate by month and by store_code.
```

## Running queries

Use DuckDB through Python and print **aggregates only** (rule 4):

```bash
python3 - <<'PY'
import duckdb
con = duckdb.connect()
con.sql("SET autoinstall_known_extensions=false")
con.sql("CREATE VIEW t AS SELECT * FROM read_csv('orders.csv', all_varchar=true)")
print(con.sql("""
  SELECT lower(trim(status)) AS status, count(*) AS n
  FROM t GROUP BY 1 ORDER BY n DESC
"""))
PY
```

- Never `SELECT *` or `LIMIT 10` from a file with PII.
- Group-by output on an identifier column is raw identifiers — don't.
- Apply the same number/date parsing the profiler used (strip currency, explicit date formats), and state it.
