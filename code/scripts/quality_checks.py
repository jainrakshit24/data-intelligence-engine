#!/usr/bin/env python3
"""Run data-quality checks and compute the Data Health Score.

    python3 quality_checks.py <path> [--rules rules.json] [--json]

Each check carries its SOURCE: "user" (from --rules) or "inferred" (proposed by
the profile). An inferred check is a suggestion, not a confirmed business rule.

Scoring (documented in references/health-scoring.md):
  check pass rate  = rows passing / rows the check applies to
  dimension score  = 100 x mean pass rate of its checks
  composite        = sum(w_i x s_i) / sum(w_i) over MEASURED dimensions only
  status           = CRITICAL if any measured dimension < floor (default 50),
                     else band: >=85 production-ready, 65-84 usable with caveats,
                     <65 remediate; "provisional" instead of a band when no
                     check comes from --rules (inferred checks cannot certify)
A dimension with no applicable check is NOT_VERIFIED: it is excluded and listed,
never scored 0 or 100.

rules.json keys (all optional):
  required: [col]           unique: [col]          ranges: {col: {min, max}}
  allowed: {col: [values]}  patterns: {col: regex} expressions: [{name, sql}]
  freshness: {column, max_age_hours}               volume: {min_rows, max_rows}
  weights: {dimension: w}   floor: 50              placeholders_are_missing: true
  schema: {col: integer|number|date|timestamp|boolean|string}
  schema_strict: false      (true: a column the schema does not declare fails)

A data contract is this file: its schema and rules are the contract's terms
(references/data-contracts.md). --fail-on-violation exits 1 when any check
from --rules fails, so the file can gate a pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
import profile_dataset as P  # noqa: E402
from _common import lit, q  # noqa: E402

DIMENSIONS = ["completeness", "validity", "uniqueness", "consistency", "timeliness", "volume"]
DEFAULT_WEIGHTS = {"completeness": 0.20, "validity": 0.20, "uniqueness": 0.20,
                   "consistency": 0.15, "timeliness": 0.15, "volume": 0.10}
SCHEMA_CASTS = {"integer": "BIGINT", "number": "DOUBLE", "date": "DATE", "timestamp": "TIMESTAMP",
                "boolean": "BOOLEAN", "string": "VARCHAR"}
EVENT_TIME_NAME = re.compile(r"(created|updated|order|event|logged|inserted|_at$|timestamp|^ts$)", re.I)


def check(dim, name, source, column, evaluated, failing, detail=""):
    rate = 1.0 if not evaluated else (evaluated - failing) / evaluated
    return {"dimension": dim, "check": name, "source": source, "column": column,
            "evaluated": evaluated, "failing": failing, "pass_rate": round(rate, 6), "detail": detail}


def value_expr(c):
    """SQL for a column's typed value, using the format mix the profile found."""
    x = q(c["name"])
    if c["kind"] == "numeric":
        return f"CAST({x} AS DOUBLE)"
    if c.get("inferred_type") in ("numeric (text)", "money (text)", "mixed: mostly numeric"):
        return P.num_expr(x)
    return x


def run(path, rules=None, sheet=None, allow_download=False) -> dict:
    rules = rules or {}
    prof = P.profile(path, sheet=sheet, allow_download=allow_download)
    if prof.get("error"):
        return prof
    rows, cols = prof["rows"], {c["name"]: c for c in prof["columns"]}
    con = _io.connect()
    src = _io.open_source(path, sheet=sheet)
    _io.create_view(con, src, allow_download)
    checks, problems, assumptions = [], [], []
    ph_missing = rules.get("placeholders_are_missing", True)
    if ph_missing:
        assumptions.append("placeholder strings (N/A, null, unknown, ...) count as MISSING for completeness; "
                           "set placeholders_are_missing=false to change")

    def need(col):
        if col not in cols:
            problems.append(f"rule names column '{col}', which is not in the data")
            return False
        return True

    # ---------------- completeness ----------------
    required = rules.get("required")
    targets = [(c, "user") for c in required if need(c)] if required else [(c, "inferred") for c in cols]
    if not required:
        assumptions.append("no 'required' list given: every column is checked for completeness (inferred)")
    for name, source in targets:
        c = cols[name]
        missing = c["null"] + c.get("blank", 0) + (c.get("placeholder", 0) if ph_missing else 0)
        checks.append(check("completeness", "not missing", source, name, rows, missing))

    # ---------------- validity ----------------
    for name, c in cols.items():
        t = c.get("inferred_type", "")
        if t in ("numeric (text)", "money (text)", "mixed: mostly numeric") and not c.get("pii"):
            checks.append(check("validity", "parses as number", "inferred", name,
                                c["present"], c["present"] - c["numeric"]))
        if t in ("date (text)", "mixed: mostly dates"):
            checks.append(check("validity", "parses as date", "inferred", name,
                                c["present"], c["present"] - c["date_any"]))
        if (t in ("date (text)", "mixed: mostly dates") or c["kind"] == "temporal") \
                and EVENT_TIME_NAME.search(name) and c.get("future") is not None:
            checks.append(check("validity", "event time not in the future", "inferred", name,
                                c["present"], c["future"], "scheduled-date columns are excluded by name"))
    for name, rng in (rules.get("ranges") or {}).items():
        if not need(name):
            continue
        v = value_expr(cols[name])
        conds = []
        if rng.get("min") is not None:
            conds.append(f"{v} >= {float(rng['min'])}")
        if rng.get("max") is not None:
            conds.append(f"{v} <= {float(rng['max'])}")
        ev, bad = con.execute(f"SELECT count({v}), count(*) FILTER (WHERE {v} IS NOT NULL AND NOT "
                              f"({' AND '.join(conds) or 'true'})) FROM src").fetchone()
        checks.append(check("validity", f"in range {rng}", "user", name, ev, bad))
    for name, allowed in (rules.get("allowed") or {}).items():
        if not need(name):
            continue
        x = q(name)
        vals = ", ".join(lit(str(a)) for a in allowed)
        ev, bad = con.execute(f"SELECT count({x}), count(*) FILTER (WHERE {x} IS NOT NULL AND "
                              f"{x} NOT IN ({vals})) FROM src").fetchone()
        checks.append(check("validity", f"value in {allowed}", "user", name, ev, bad, "exact match, case-sensitive"))
    for name, pattern in (rules.get("patterns") or {}).items():
        if not need(name):
            continue
        x = q(name)
        ev, bad = con.execute(f"SELECT count({x}), count(*) FILTER (WHERE {x} IS NOT NULL AND NOT "
                              f"regexp_full_match({x}, {lit(pattern)})) FROM src").fetchone()
        checks.append(check("validity", "matches pattern", "user", name, ev, bad))

    schema = rules.get("schema") or {}
    for name, typ in schema.items():
        if typ not in SCHEMA_CASTS:
            problems.append(f"schema: '{name}' has type '{typ}'; use one of {', '.join(SCHEMA_CASTS)}")
            continue
        if name not in cols:
            checks.append(check("validity", "column present (schema)", "user", name, 1, 1, "missing from the data"))
            continue
        if typ == "string":
            continue
        s_ = f"trim(CAST({q(name)} AS VARCHAR))"
        ph = ", ".join(lit(p) for p in _io.PLACEHOLDERS) if ph_missing else "''"
        ev, bad = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE TRY_CAST({s_} AS {SCHEMA_CASTS[typ]}) IS NULL) FROM src "
            f"WHERE {q(name)} IS NOT NULL AND {s_} <> '' AND lower({s_}) NOT IN ({ph})").fetchone()
        checks.append(check("validity", f"is {typ} (schema)", "user", name, ev, bad,
                            "strict cast: no currency symbols or thousands separators; dates ISO"))
    if schema and rules.get("schema_strict"):
        for name in cols:
            if name not in schema:
                checks.append(check("validity", "declared in schema", "user", name, 1, 1,
                                    "schema_strict: column not in the contract"))

    # ---------------- uniqueness ----------------
    allcols = ", ".join(q(c) for c in cols)
    extra = con.execute(f"SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) n FROM src "
                        f"GROUP BY {allcols} HAVING count(*) > 1)").fetchone()[0]
    checks.append(check("uniqueness", "no exact duplicate rows", "inferred", "*", rows, extra))
    unique = list(rules.get("unique") or [])
    keys = [(k, "user") for k in unique if need(k)]
    keys += [(n, "inferred") for n, c in cols.items() if c.get("key_candidate") and n not in unique]
    for name, source in keys:
        c = cols[name]
        checks.append(check("uniqueness", "key is unique", source, name, c["nonnull"],
                            c["nonnull"] - c["distinct"]))

    # ---------------- consistency ----------------
    for name, c in cols.items():
        if c["kind"] == "text" and c.get("inferred_type") == "categorical" \
                and c.get("distinct_folded") is not None and c["distinct_folded"] < c["distinct"]:
            x = q(name)
            bad = con.execute(
                f"WITH g AS (SELECT lower(trim({x})) f, {x} v, count(*) n FROM src WHERE {x} IS NOT NULL "
                f"GROUP BY 1, 2), m AS (SELECT sum(n) tot, max(n) mx FROM g GROUP BY f) "
                f"SELECT coalesce(sum(tot - mx), 0) FROM m").fetchone()[0]
            checks.append(check("consistency", "one spelling per value (case/whitespace)", "inferred",
                                name, c["nonnull"], bad, "non-canonical spellings vs the most common one"))
        fm = c.get("date_formats") or {}
        if c.get("inferred_type") in ("date (text)", "mixed: mostly dates") and len(fm) > 1:
            dominant = max(fm.values())
            checks.append(check("consistency", "one date format", "inferred", name,
                                c["present"], c["present"] - dominant, f"dominant {max(fm, key=fm.get)}"))
    for e in rules.get("expressions") or []:
        err = _io.check_expression(e.get("sql", ""))
        if err:
            problems.append(f"expression '{e.get('name')}': {err}")
            continue
        try:
            ev, good = con.execute(f"SELECT count(*) FILTER (WHERE ({e['sql']}) IS NOT NULL), "
                                   f"count(*) FILTER (WHERE ({e['sql']})) FROM src").fetchone()
        except Exception as ex:
            problems.append(f"expression '{e.get('name')}' failed: {type(ex).__name__}: {str(ex)[:160]}")
            continue
        checks.append(check("consistency", e.get("name", "expression"), "user", "-", ev, ev - good, e["sql"]))

    # ---------------- timeliness ----------------
    fr = rules.get("freshness")
    if fr and need(fr.get("column", "")):
        c = cols[fr["column"]]
        dv = P.date_value_expr(c) or f"TRY_CAST({q(c['name'])} AS TIMESTAMP)"
        tv = dv.replace("CAST(coalesce", "CAST(coalesce", 1).replace(" AS DATE)", " AS TIMESTAMP)")
        latest, age_h = con.execute(f"SELECT CAST(max({tv}) AS VARCHAR), "
                                    f"date_diff('minute', max({tv}), CAST(current_timestamp AS TIMESTAMP)) / 60.0 "
                                    f"FROM src").fetchone()
        ok = age_h is not None and age_h <= float(fr["max_age_hours"])
        checks.append(check("timeliness", f"latest {fr['column']} within {fr['max_age_hours']}h", "user",
                            fr["column"], 1, 0 if ok else 1,
                            f"latest {latest}, age {age_h:,.1f}h" if age_h is not None else "no parseable timestamp"))

    # ---------------- volume ----------------
    vol = rules.get("volume")
    if vol:
        lo, hi = vol.get("min_rows"), vol.get("max_rows")
        ok = (lo is None or rows >= lo) and (hi is None or rows <= hi)
        checks.append(check("volume", f"row count in [{lo}, {hi}]", "user", "*", 1, 0 if ok else 1,
                            f"{rows:,} rows"))

    # A user rule that silently skipped rows covers less than it appears to (rule A3)
    for c in checks:
        if c["source"] == "user" and c["dimension"] in ("validity", "uniqueness", "consistency") \
                and c["evaluated"] < rows:
            c["not_evaluated"] = rows - c["evaluated"]

    return {"checks": checks, **score(checks, rules), "rows": rows, "problems": problems,
            "assumptions": assumptions, "risk_triggers": prof["risk_triggers"], "coverage": prof["coverage"]}


def score(checks, rules) -> dict:
    weights = {**DEFAULT_WEIGHTS, **(rules.get("weights") or {})}
    floor = float(rules.get("floor", 50))
    dims, excluded = {}, {}
    for d in DIMENSIONS:
        cs = [c for c in checks if c["dimension"] == d]
        if not cs:
            excluded[d] = {"timeliness": "NOT_VERIFIED: no freshness rule (needs a timestamp column + max age)",
                           "volume": "NOT_VERIFIED: one snapshot, no expected row range or history"}.get(
                d, "NOT_VERIFIED: no applicable check")
            continue
        dims[d] = round(100 * sum(c["pass_rate"] for c in cs) / len(cs), 1)
    wsum = sum(weights[d] for d in dims)
    composite = round(sum(weights[d] * s for d, s in dims.items()) / wsum, 1) if wsum else None
    below = [d for d, s in dims.items() if s < floor]
    if composite is None:
        band = "NOT_VERIFIED"
    elif below:
        band = "CRITICAL"
    elif composite >= 85:
        band = "production-ready"
    elif composite >= 65:
        band = "usable with caveats"
    else:
        band = "remediate before use"
    # Inferred checks alone are proposals: they cannot certify data as ready (rule A3)
    provisional = not any(c["source"] == "user" for c in checks)
    status = "provisional" if provisional and band not in ("CRITICAL", "NOT_VERIFIED") else band
    # A dimension mean can hide one broken check, just as the composite can hide a dimension
    weak = sorted((c for c in checks if 100 * c["pass_rate"] < floor), key=lambda c: c["pass_rate"])
    return {"dimensions": dims, "excluded": excluded, "weights": weights, "floor": floor,
            "composite": composite, "status": status, "band": band, "provisional": provisional,
            "below_floor": below,
            "weak_checks": [{k: c[k] for k in ("dimension", "check", "column", "pass_rate")} for c in weak]}


def render(r) -> str:
    L = [f"DATA HEALTH SCORE: {r['composite']}/100  —  {r['status'].upper()}  "
         f"({len(r['dimensions'])} of {len(DIMENSIONS)} dimensions measured)"]
    if r["provisional"] and r["status"] == "provisional":
        L.append(f"  PROVISIONAL because every check is inferred — no business rule confirmed "
                 f"(band would be: {r['band']}). Pass --rules to certify.")
    if r["below_floor"]:
        L.append(f"  CRITICAL because {', '.join(r['below_floor'])} < floor {r['floor']:g} "
                 "(an average must not hide a broken dimension)")
    if r["weak_checks"]:
        L.append(f"  checks below {r['floor']:g}% hidden inside the averages: " + "; ".join(
            f"{c['column']} {c['check']} {100 * c['pass_rate']:.1f}%" for c in r["weak_checks"][:5])
            + (f" (+{len(r['weak_checks']) - 5} more)" if len(r["weak_checks"]) > 5 else ""))
    L.append("")
    for d in DIMENSIONS:
        if d in r["dimensions"]:
            L.append(f"  {d:<13} {r['dimensions'][d]:>5.1f}   weight {r['weights'][d]:.2f}")
        else:
            L.append(f"  {d:<13}   —     {r['excluded'][d]}")
    L += ["", "CHECKS  [source] dimension · check · column · pass rate · failing/evaluated"]
    for c in sorted(r["checks"], key=lambda c: (DIMENSIONS.index(c["dimension"]), c["pass_rate"])):
        flag = "  " if c["pass_rate"] >= 0.999 else "✗ "
        L.append(f"  {flag}[{c['source']:<8}] {c['dimension']:<12} {c['check']:<42.42} {c['column']:<14.14} "
                 f"{100 * c['pass_rate']:6.2f}%  {c['failing']:,}/{c['evaluated']:,}"
                 + (f"  ({c['detail']})" if c["detail"] and c["pass_rate"] < 0.999 else ""))
    partial = [c for c in r["checks"] if c.get("not_evaluated")]
    if partial:
        L += ["", "NOT EVALUATED  (user rules that could not judge every row — their pass rate covers fewer rows)"]
        for c in partial:
            L.append(f"  - {c['check']} on {c['column']}: {c['not_evaluated']:,} of {r['rows']:,} rows skipped "
                     f"({_io.pct(c['not_evaluated'], r['rows'])}) — value missing, or unparseable by the rule")
    if r["problems"]:
        L += ["", "RULE PROBLEMS"] + [f"  - {p}" for p in r["problems"]]
    if r["assumptions"]:
        L += ["", "ASSUMPTIONS"] + [f"  - {a}" for a in r["assumptions"]]
    L += ["", "Inferred checks are proposals, not confirmed business rules. Confirm them by moving them into rules.json.",
          "", r["coverage"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--rules")
    ap.add_argument("--sheet")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-violation", action="store_true",
                    help="exit 1 if any check from --rules fails (contract gate)")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    rules = {}
    if a.rules:
        try:
            with open(a.rules) as f:
                rules = json.load(f)
        except (OSError, ValueError) as e:
            print(f"cannot use rules file {a.rules}: {e}. Nothing was checked.", file=sys.stderr)
            return _io.EXIT_USAGE
        if not isinstance(rules, dict):
            print(f"rules file {a.rules} must hold a JSON object. Nothing was checked.", file=sys.stderr)
            return _io.EXIT_USAGE
    r = run(a.path, rules, a.sheet, a.allow_extension_download)
    if r.get("error"):
        print(r["message"], file=sys.stderr)
        return _io.EXIT_EXTENSION_REQUIRED
    if a.json:
        _io.emit_json(r)
    else:
        print(render(r))
    if a.fail_on_violation and any(c["source"] == "user" and c["failing"] for c in r["checks"]):
        return _io.EXIT_FINDINGS
    return 0


if __name__ == "__main__":
    sys.exit(main())
