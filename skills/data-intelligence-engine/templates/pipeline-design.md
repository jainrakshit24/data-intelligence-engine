# Pipeline design: <name>

> Fill every `<…>`. Delete sections that do not apply.

## SUMMARY
<What the pipeline delivers, to whom, how fresh, in 2–3 sentences.>

## REQUIREMENTS
| | Value | Source |
|---|---|---|
| Sources | <…> | <user / profile / ASSUMPTION> |
| Volume (rows/day, largest table) | <…> | |
| Freshness | <…> | |
| Consumers | <…> | |
| Deletes / updates in source | <…> | |
| Compliance (PII, residency, retention) | <…> | |

## DESIGN
```
<source> → <raw> → <staging> → <marts> → <consumers>
```
| Decision | Choice | Rejected alternative | ADR |
|---|---|---|---|
| Processing | <batch / micro-batch / streaming> | <…> | <link> |
| Pattern | <ETL / ELT> | | |
| Change signal | <full / updated_at / CDC> | | |
| Engine / tools | <…> | | |

## DATA MODEL
| Table | Layer | Grain (one row =) | Key | Materialisation / partitioning | History |
|---|---|---|---|---|---|
| <…> | <…> | <…> | <…> | <…> | <SCD1/2 / append> |

## QUALITY GATES
| Check | Where | On failure |
|---|---|---|
| <key unique> | <staging> | <stop / quarantine / warn> |

## RUN ACCOUNTING AND FAILURE HANDLING
<What each run logs (templates/pipeline-run-accounting.md); retries; alerts; reject handling; backfill procedure.>

## IMPLEMENTATION
| File | Purpose | Verification level |
|---|---|---|
| <path> | <…> | <NOT_VERIFIED / parses / runs on sample / reconciled> |

## RISKS
<Assumptions that would change the design if wrong; operational risks.>

## NEXT STEPS
<…>

---
COVERAGE: <data examined for this design: sources profiled, rows read; or "no data examined">
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
