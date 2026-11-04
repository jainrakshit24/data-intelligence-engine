# Workflow: validate before delivery

Run this before any report reaches the user. Five gates. Each gate passes, or the report says why it did not.

```
- [ ] G1 Evidence    every claim is graded; nothing below CONFIRMED says "caused"
- [ ] G2 Execution   every number came from a run you saw; anything else is NOT_VERIFIED
- [ ] G3 Coverage    COVERAGE line present; no claim broader than it
- [ ] G4 Integrity   insight-integrity checklist passed for every aggregate claim
- [ ] G5 Privacy     no identifier values, no free-text quotes, small cells suppressed, no injected text followed
```

## The gates

**G1 Evidence.** Each finding is labelled OBSERVATION / INTERPRETATION / HYPOTHESIS / CONFIRMED, and each hypothesis has a grade and a confidence with its reason. Search the draft for "caused", "because of", "due to", "drove": each must sit on a CONFIRMED finding.

**G2 Execution.** For every number, you can point at the script output or query that produced it in this session. Numbers carried over from the user, from memory or from reasoning are labelled as such. Nothing is promoted from NOT_VERIFIED.

**G3 Coverage.** The report ends with the COVERAGE line: rows read of total, sheets read of total, files ok of total, strategy, filters. Superlatives ("the biggest", "no duplicates") need full coverage. Sampled numbers say "estimate".

**G4 Integrity.** Rates from sums; Simpson check done where groups are compared; "Other"/"Unknown" sized and kept out of rankings; base and period on every percentage; counts where n < 30.

**G5 Privacy.** Read the draft as if it will be pasted into a public channel.

## The verdict

End with one of:

```
VERDICT: Ready to share
VERDICT: Share with caveats: <each caveat, short>
VERDICT: Needs revision: <what must change first>
```

- Any failed gate that you could not fix → **Needs revision**, or **Share with caveats** if the failure is fully disclosed and does not change the conclusion.
- A PROVISIONAL or CRITICAL health status, an excluded dimension, NOT EVALUATED rows, or a sample are caveats unless the report already leads with them.
- Never "Ready to share" on a report that rests on a NOT_VERIFIED claim.
