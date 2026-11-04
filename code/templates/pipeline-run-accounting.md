# Run accounting: <pipeline> · <run id / interval>

> One per run, or per verification. The numbers come from the job's logs or from `scripts/reconcile.py`.

| | |
|---|---|
| Interval | <start> → <end> (<timezone>) |
| Watermark | <before> → <after> |
| Started / finished | <…> / <…> (<duration>) |
| Status | <success / failed at step …> |

## ROWS
| Step | In | Out | Rejected (reason) |
|---|---|---|---|
| Extract | — | <n> | <…> |
| Staging | <n> | <n> | <n (null key / bad type / …)> |
| Mart | <n> | <n> | <…> |

## RECONCILIATION (source → target)
```
source rows        <n>
− dropped keys     <n>  (<k> keys)
+ new keys         <n>
− collapsed dups   <n>
+ fan-out          <n>   <must be 0 unless intended>
± null keys        <n>
= target rows      <n>   <✓ explained / ✗ unexplained n>
```
| Measure | Source | Target | Delta | Explained by |
|---|---|---|---|---|
| <sum(amount)> | <…> | <…> | <…> | <dropped / new / changed / duplicates> |

## CHECKS
| Check | Result |
|---|---|
| <key unique> | <pass / fail (n)> |

## NOTES
<Anything unusual: late data, schema changes, manual reruns.>

---
COVERAGE: <rows read>/<total> · <files/partitions ok>/<total> · filters: <…>
VERDICT: <Ready to share | Share with caveats: … | Needs revision: …>
