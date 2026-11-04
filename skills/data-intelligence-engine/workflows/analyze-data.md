# Workflow: analyze data

For EDA and GENERAL_DATA_INVESTIGATION. Load `references/eda.md` and `references/insight-integrity.md` (EDA), or `references/data-quality.md` (investigation).

```
- [ ] 1. Questions: write 3–5 (or the user's question, restated)
- [ ] 2. Profile (profile-dataset.md, steps 1–6)
- [ ] 3. Grain: what is one row; is the key unique
- [ ] 4. Climb the EDA ladder only as far as the questions need
- [ ] 5. For an investigation: list hypotheses, then test each
- [ ] 6. Run the insight-integrity checklist on every finding
- [ ] 7. Write findings: FINDING · EVIDENCE · MEANING · CONFIDENCE · NEXT CHECK
- [ ] 8. validate-before-delivery.md
```

## Steps

1. **Questions.** For "analyze this CSV" with no question, infer what the data is for and say what you assumed.
2. **Profile.** The profile's risk triggers decide what every later number must account for (placeholders, duplicates, mixed dates).
3. **Grain.** If the key repeats, decide — and state — whether you count rows or unique keys. It changes every rate.
4. **EDA ladder.** Univariate (from the profile) → segments → relationships → time. Aggregate-only queries (`eda.md`, "Running queries").
5. **Investigation** ("why did X change?"):
   - State the observation with numbers and periods.
   - List the candidate explanations before querying: data-side (late load, duplicates, filter, definition change, missingness) before business-side.
   - Test each with one query; grade it SUPPORTED / PARTIALLY_SUPPORTED / REJECTED / NOT_VERIFIED.
   - Data-side causes first: a pipeline problem looks exactly like a business change.
   - If the cause sits in a pipeline, say the dedicated debugging module is planned for Phase 3, give general guidance, and label it.
6. **Integrity.** Every average from sums; Simpson check on comparisons; "Other"/"Unknown" out of rankings; counts when n < 30; no causal verbs below CONFIRMED.
7. **Write.** At most a handful of findings, ranked by what the reader should act on.
8. **Validate.**
