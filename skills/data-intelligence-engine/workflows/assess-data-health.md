# Workflow: assess data health

For DATA_QUALITY. Load `references/data-quality.md` and `references/health-scoring.md`.

Pick the mode first:
- **Full audit** — a new or unfamiliar dataset: every step below.
- **Targeted scan** — "this column broke": profile, then only the checks for that column and its neighbours; still report coverage.
- **Monitoring setup** — recurring checks: write `rules.json` (with freshness and volume), then hand over the command for the scheduler (`quality_checks.py … --json`, alert when `status` is CRITICAL or a dimension drops). The skill does not run the schedule itself.

```
- [ ] 1. Rules: from data-context.md, the user, or none (→ provisional)
- [ ] 2. Write rules.json if any rules exist
- [ ] 3. Run quality_checks.py [--rules rules.json]
- [ ] 4. Read NOT EVALUATED and RULE PROBLEMS before the score
- [ ] 5. Run detect_duplicates.py on each unique key that failed
- [ ] 6. Write the report (templates/data-health-report.md)
- [ ] 7. Offer to save confirmed rules (build-data-context.md)
- [ ] 8. validate-before-delivery.md
```

## Steps

1. **Rules.** Business rules come from `data-context.md` or the user. Never invent one and label it `user`.
2. **rules.json.** Schema in `data-quality.md`. Freshness and volume need numbers only the user knows (max age, expected row range); without them those dimensions stay NOT_VERIFIED.
3. **Run.** `python3 scripts/quality_checks.py <path> --rules rules.json`.
4. **Read the gaps first.**
   - NOT EVALUATED: a rule that skipped rows. Fix the rule if you can (parse the right date format) and re-run; otherwise report the skipped share beside the pass rate.
   - RULE PROBLEMS: a rule that did not run. Fix it or report it.
5. **Duplicates.** For a failing uniqueness check, `detect_duplicates.py --key <col>` tells pure copies from conflicting versions.
6. **Report.** Score line exactly as the script states it — including PROVISIONAL, CRITICAL and "N of 6 measured". Lead with the weakest dimension and the check behind it. Every inferred check is labelled as a proposal.
7. **Save.** If the user confirmed rules along the way, offer `build-data-context.md`.
8. **Validate.**

## Never

- Round a CRITICAL or PROVISIONAL status into a friendlier word.
- Drop an excluded dimension from the report.
- Change weights or the floor to move the band.
