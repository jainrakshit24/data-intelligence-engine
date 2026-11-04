# Workflow: profile a dataset

For DATA_PROFILE. Copy the checklist into your working notes and tick it off.

```
- [ ] 1. Context: read data-context.md if it exists
- [ ] 2. First look: dataset_summary.py
- [ ] 3. Choose read strategy (references/large-data-strategy.md)
- [ ] 4. Profile: profile_dataset.py
- [ ] 5. Keys: detect_duplicates.py --key <col> for each key candidate
- [ ] 6. PII: if any column is listed, load references/privacy-and-pii.md
- [ ] 7. Write the profile (templates/data-profile.md)
- [ ] 8. validate-before-delivery.md
```

## Steps

1. **Context.** If `data-context.md` exists, its column meanings, placeholders and rules override what the profile infers. Note any conflict as a finding ("context says `status` has 3 values; data has 8 spellings").
2. **First look.** `python3 scripts/dataset_summary.py <path>`. One scan: rows, columns, missingness. For `.xlsx` it lists sheets and declared row counts even without the extension.
3. **Strategy.** Under 1 GiB: whole file. Larger: still whole and streamed, but expect `≈` on non-key distincts. Only sample (`--sample-rows`) if the user wants speed over exactness, and say so.
4. **Profile.** `python3 scripts/profile_dataset.py <path> [--sheet …]`. Do not open the file any other way (rule 4).
5. **Keys.** For each column the profile calls a key candidate, or that `data-context.md` names as a key: `python3 scripts/detect_duplicates.py <path> --key <col>`. Pure copies vs conflicting versions change the advice.
6. **PII.** Any PII line → load `references/privacy-and-pii.md` before writing about those columns.
7. **Write.** Fill `templates/data-profile.md`. Lead with what someone must know before using the data (the risk triggers that matter), not with the column list.
8. **Validate** with `workflows/validate-before-delivery.md`.

## Stop and say so when

- The script exits 3 (no DuckDB): give the install command; do not read the file yourself.
- The script exits 4 (extension needed): ask for consent to download, or for a CSV/Parquet export.
- The file cannot be read (exit 5): report the error; never guess its contents.
