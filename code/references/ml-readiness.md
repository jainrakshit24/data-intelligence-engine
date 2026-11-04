# ML readiness

Load this for ML_DATA_PREPARATION and MODEL_READY_DATASET, and for any "build / train a model" request: do this data-side work, then state the boundary. The workflow is `workflows/ml-readiness.md`; the report is `templates/ml-readiness-report.md`.

**Scope (decision D1):** the skill checks and prepares the *data*. It never trains, tunes, evaluates, serves or monitors a model, and never writes code that pretends to. After the readiness report, say plainly: "Model training is outside this skill. The data is <verdict>; the next step is <…>."

## Contents
- The prediction contract
- Running the check
- Leakage: the four signals
- Target and class balance
- Splits
- Preparing features
- Reading the verdict
- What the check cannot see

## The prediction contract

Before any check, write down four things (ask the user for the ones the data cannot show):

| Term | Question | Example |
|---|---|---|
| Prediction moment | When will the model be asked? | Each customer, on the 1st of the month |
| Target and horizon | What is predicted, over what window after that moment? | Churns within the next 30 days |
| Label availability | When is the true label known? | 30 days after the prediction moment, so the last month has no labels yet |
| Feature cut-off | Which data may a feature use? | Only what was recorded **before** the prediction moment |

Every leakage test is one question: **was this feature available at the prediction moment?** A row-level dataset should carry the prediction moment as a column (a snapshot date). Without one, leakage by time cannot be checked; say so.

## Running the check

```bash
python3 scripts/ml_readiness.py customers.csv --target churned --positive yes \
    --prediction-time snapshot_date --feature-time nps_score=nps_date \
    --time snapshot_date --split split --group household_id
```

| Flag | Use |
|---|---|
| `--target` | The label column. Rows without one are counted and excluded |
| `--positive` | The positive class of a binary target (default: the smaller class) |
| `--prediction-time` | The prediction moment per row. Date features later than it are flagged |
| `--feature-time F=T` | Feature `F` was recorded at time `T` (a score with its survey date). Repeatable |
| `--time` | Time column for label-rate-by-month and the time-split checks |
| `--split` | Existing train/test(/validation) column. The value `train`, or the largest, is training |
| `--group` | Entity whose rows must stay on one side of the split (customer, household, patient) |

It prints column names and aggregates only, never feature values. A class with fewer than 5 rows is shown as "(rare)".

## Leakage: the four signals

| Signal | What the script measures | Typical cause |
|---|---|---|
| **Separates the target alone** | AUC of one feature vs a binary target (numbers and dates by rank; categories by their own positive rate); \|Spearman\| for a numeric target; purity gain for multiclass. ≥ 0.98 is a BLOCKER; 0.90–0.98 a CHECK | A column filled because of the outcome: refund amount, cancellation reason, final status |
| **Missingness encodes the outcome** | Missing share per class. If being missing alone separates the classes (AUC ≥ 0.98) it is a BLOCKER; a gap ≥ 20 points is a CHECK | A field filled only for one outcome (cancel date, closing note) |
| **Dated after the prediction moment** | Rows where a date feature, or a `--feature-time` timestamp, is later than `--prediction-time` | Last login, survey score or balance taken after the snapshot |
| **Name suggests post-outcome** | Names like refund, cancel, churn, outcome, result, closed, final, chargeback | Usually right; always confirm |

A high single-feature AUC is evidence, not proof. Some real predictors are that strong (a fraud rule the business already applies). The script cannot tell; the data owner can. That is why the report lists each one with its number and the question to ask.

Separation for categories is in-sample: a category with few rows scores its own rows perfectly. So categories are scored only up to 50 distinct values or 5% of rows. High-cardinality IDs are flagged as identifiers instead.

## Target and class balance

- **Kind**: binary (2 values), multiclass, regression (a number with > 20 values), or constant (BLOCKER: nothing to learn).
- **Unlabelled rows**: excluded and counted. If they are the most recent period, that is label delay; keep them for scoring later, never fill them.
- **Imbalance** below 10%: accuracy is meaningless (99% "no" scores 99%). Report PR-AUC, recall at a fixed precision, or cost; stratify the split.
- **Events per feature**: fewer than about 10 minority rows per feature makes overfitting likely. Fewer features or more data.
- **Label drift**: label rate by month (with `--time`). A rate that moved means the base rate the model learns is already out of date.

## Splits

| Problem | Check | Why it matters |
|---|---|---|
| Random split on time-dependent data | Evaluation rows older than the newest training row | The model sees the future in training; offline accuracy is higher than it will be live |
| Group leakage | `--group` values in both training and evaluation (BLOCKER) | The model recognises the customer, not the pattern |
| Duplicates across the split | Duplicate feature rows | Same as above, row by row |
| Same features, different labels | Conflicting rows | Label noise, or a feature that would explain the difference is missing |

Default split for anything with a time column: **train on earlier, validate on later, test on the latest**, with groups kept whole. Leave a gap at least as long as the label horizon between train and test, so training labels do not reach into the test period.

## Preparing features

When the user asks for preparation (ML_DATA_PREPARATION), produce **code, labelled NOT_VERIFIED until it runs**, that:

1. Drops identifiers, constants and every BLOCKER column (or the ones the owner confirmed as leaks), and lists what was dropped and why.
2. Splits **first**, then fits every learned transformation (imputation values, scaling, target or frequency encoding, category vocabularies) **on training data only** and applies it to the rest. Fitting on all rows leaks the test set into training.
3. Imputes with a recorded rule, and adds a missing-indicator column where missingness differs by class and is *not* post-outcome.
4. Encodes categories: one-hot for few values, frequency or target encoding (fitted on training folds only) for many, with an "unseen" bucket.
5. Keeps the point-in-time rule for every join: a feature table joins on `feature_time <= prediction_time`, the latest such row (an as-of join), never the latest row overall.
6. Writes the prepared data to new files; the source is never changed (rule 3).

Then re-run `ml_readiness.py` on the prepared training set: the verdict should have no BLOCKER left.

## Reading the verdict

| Verdict | Meaning |
|---|---|
| NOT READY | At least one blocker: a suspected leak, a constant target or groups across the split. Training now would give a model that looks good and fails live |
| READY AFTER CHECKS | No blocker, but questions only the data owner can answer (availability, names, time overlap) |
| READY WITH CAVEATS | Only warnings: imbalance, identifiers to drop, duplicates, few events |
| READY | Nothing found. Still not proof of no leakage; see below |

## What the check cannot see

- **Leaks spread over several columns**, each weak alone. Ask how each feature is produced.
- **Leaks in meaning**: a column computed with knowledge of the outcome but not correlated with it on this sample.
- **Whether the training population matches the scoring population** (who will be scored live). Compare with `drift_check.py` against a recent scoring extract.
- **Anything about the model.** Training, evaluation and deployment are out of scope.
