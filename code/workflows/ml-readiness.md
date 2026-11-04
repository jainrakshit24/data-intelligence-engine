# Workflow: ML readiness

For MODEL_READY_DATASET, ML_DATA_PREPARATION, and any request to build or train a model. Load `references/ml-readiness.md`, plus `references/data-profiling.md` and `references/data-quality.md`; add `references/privacy-and-pii.md` if personal data is in the features.

```
- [ ] 1. Prediction contract: moment, target + horizon, label delay, feature cut-off
- [ ] 2. Profile the dataset (profile_dataset.py)
- [ ] 3. Run ml_readiness.py with every flag the data supports
- [ ] 4. For each BLOCKER and CHECK: the question for the data owner
- [ ] 5. Preparation (if asked): drop, split, fit on train, encode; code labelled NOT_VERIFIED
- [ ] 6. Re-run ml_readiness.py on the prepared training data
- [ ] 7. Report (templates/ml-readiness-report.md), ending with the scope boundary
- [ ] 8. validate-before-delivery.md
```

## Steps

1. **Contract.** If there is no prediction-moment column, ask what it is. If none exists, say that time-based leakage cannot be checked, and carry that into the verdict.
2. **Profile.** Types, missingness, PII and key candidates come from the profile; the readiness check reuses them.
3. **Run.** `python3 scripts/ml_readiness.py <data> --target <y> [--positive …] [--prediction-time …] [--feature-time F=T …] [--time …] [--split …] [--group …]`. A missing flag means a check did not run; list it under NOT CHECKED.
4. **Questions.** Turn each blocker and check into one question: "Is `refund_amount` known before the snapshot date, or only after a customer churns?" Grade the leak as SUSPECTED until the owner answers; CONFIRMED only when they do or a timestamp proves it.
5. **Prepare.** Only when asked. Follow "Preparing features" in the reference. Split before fitting anything.
6. **Re-check.** The prepared training data should have no blocker.
7. **Report.** Verdict exactly as the script printed it. End with: "Model training is outside this skill. The data is <verdict>; the next step is <…>."
8. **Validate.**

## Never

- Train, tune or evaluate a model, or write code that pretends to (D1).
- Call a dataset READY because no blocker was found when `--prediction-time` was not given; say the time checks did not run.
- Fit an imputer, scaler or encoder on all rows before splitting.
- Print feature values or identifiers while investigating a leak.
