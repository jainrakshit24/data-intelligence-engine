# Workflow: clean data

For DATA_CLEANING. Load `references/data-cleaning.md` first. Nothing changes until step 5.

```
- [ ] 1. Profile the original (profile-dataset.md, steps 1–6)
- [ ] 2. Record the original's size and SHA-256
- [ ] 3. Build the proposal table: issue · change · rows affected · reversible · rationale
- [ ] 4. Get approval (or cite the data-context.md policy)
- [ ] 5. Write ONE SQL file; run it; output goes to a NEW file
- [ ] 6. Verify: re-profile the output, reconcile rows, re-check the original's SHA-256
- [ ] 7. Write the cleaning report (templates/cleaning-report.md)
- [ ] 8. validate-before-delivery.md
```

## Steps

1. **Profile.** Every proposed change must trace to a profile trigger or a duplicate-check result.
2. **Fingerprint the original.**
   ```bash
   python3 -c "import hashlib,os,sys; p=sys.argv[1]; print(os.path.getsize(p), hashlib.sha256(open(p,'rb').read()).hexdigest())" <path>
   ```
   For files over a few GB, hash in chunks or compare size and modification time instead, and say which.
3. **Proposal.** Use the fix catalogue in `data-cleaning.md`. Every row has an exact count. Put the decisions only the user can make at the top: which placeholders mean "missing", which version of a duplicated key wins, which date format a source uses.
4. **Approval.** Show the table and wait. If the user approves part, do that part only. If `data-context.md` grants a standing policy, quote it.
5. **Execute.** One SQL file (`clean_<name>.sql`) with a `COPY (…) TO '<name>.cleaned.csv'`. Run it with the one-liner in `data-cleaning.md`. Never write to the original's path.
6. **Verify.**
   - `profile_dataset.py <name>.cleaned.csv`: each fixed trigger is gone; no new one appeared.
   - Rows: `original − removed = cleaned`, exactly; explain every removed row.
   - Original: same size and SHA-256 as step 2.
   If any check fails, say so and do not call the clean done.
7. **Report.** `templates/cleaning-report.md`: before/after counts per change, the SQL file name, what was deliberately left alone.
8. **Validate.**

## Stop and say so when

- A change needs a business decision you do not have (which duplicate wins, what a code means). Propose, don't decide.
- Verification fails. Report the failure with its numbers.
