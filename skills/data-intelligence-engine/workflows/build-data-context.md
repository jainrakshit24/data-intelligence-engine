# Workflow: build data-context.md

Use when the user confirms definitions, rules or policies and wants them remembered. `data-context.md` lives in the user's project root and is read first on every later request.

```
- [ ] 1. Collect only what the user CONFIRMED in this session (or wrote themselves)
- [ ] 2. Start from templates/data-context.md
- [ ] 3. If data-context.md exists, merge — never drop what is there; show conflicts
- [ ] 4. Show the diff and get approval before writing
- [ ] 5. Write it; tell the user where it is
```

## What belongs in it

- Dataset purpose, grain (what one row is), and keys.
- Column meanings that were ambiguous ("`amount` is in INR, includes tax").
- Which strings mean "missing" for this source.
- Date formats per source.
- Business rules — ready to copy into `rules.json`.
- Policies that grant standing approval ("trimming whitespace is always OK").
- Known issues already accepted ("legacy_flag is deprecated; ignore it").

## What never belongs in it

- Raw data values that identify anyone.
- Inferred checks that the user did not confirm. Mark anything uncertain as `UNCONFIRMED` or leave it out.
- Credentials or connection strings.

## Conflicts

If the data contradicts `data-context.md` ("context says 3 status values; data has 8 spellings"), report it as a finding. Do not edit the context to match the data unless the user says the context is wrong.
