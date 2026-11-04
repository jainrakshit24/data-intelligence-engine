#!/usr/bin/env python3
"""Compare a current dataset with a baseline: schema changes and distribution drift.

    python3 drift_check.py <baseline> <current> [--columns a,b] [--bins 10]
                           [--fail-on moderate|major] [--json]

SCHEMA    removed column ........................ BREAKING
          type family changed (number/date/text/boolean) BREAKING
          added column .......................... additive
          removed + added with the same type, missing share and distinct
          ratio .................................. possible rename (verify)
DRIFT     per shared column of the same type family:
          missing share (null, blank, placeholder) with a two-proportion z
          numbers: PSI over the baseline's deciles; mean, median, p95; a
                   median ratio near 10^k is reported as a possible unit change;
                   a mean that moved >= 3 standard errors and >= 10% (50%: major)
                   while the deciles held is a change in the tail
          categories (<= 50 values in the baseline): PSI over the baseline's
                   categories plus one bucket for values the baseline never had
          identifiers, personal data and free text: missing share and distinct
                   ratio only; their values are never compared or printed
SEVERITY  PSI < 0.10 stable · 0.10-0.25 moderate · >= 0.25 major (industry
          convention). Missing share: z >= 3 and a change >= 1 point is
          moderate, >= 10 points major. Under 100 values on either side, PSI is
          marked low-sample.

Exit codes: 0 ok · 1 --fail-on reached (a breaking change always counts) ·
2 usage · 3 no duckdb · 5 unreadable file.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
import profile_dataset as P  # noqa: E402
from _common import lit, q  # noqa: E402

PSI_MODERATE, PSI_MAJOR = 0.10, 0.25
PSI_EPS = 1e-4            # share used for an empty bin, so ln() stays finite
LOW_SAMPLE = 100
CATEGORY_MAX = 50
RANK = {"stable": 0, "moderate": 1, "major": 2}
MEAN_MODERATE, MEAN_MAJOR = 0.10, 0.50  # relative mean change, when also >= 3 standard errors


def family(c: dict) -> str:
    if c["kind"] == "text" and c.get("inferred_type") == "empty":
        return "unknown"  # no values: the type cannot be known, so it cannot have changed
    if c["kind"] == "numeric":
        return "number"
    if c["kind"] == "temporal":
        return "date"
    if c["kind"] == "boolean":
        return "boolean"
    t = c.get("inferred_type", "")
    if t in ("numeric (text)", "money (text)", "mixed: mostly numeric"):
        return "number"
    if t in ("date (text)", "mixed: mostly dates"):
        return "date"
    return "text"


def missing(c: dict) -> int:
    return c["null"] + c.get("blank", 0) + c.get("placeholder", 0)


def comparable_values(c: dict) -> bool:
    """Distributions are compared only for columns that do not identify a person on their own.

    Quasi-identifiers (age, gender, postcode) are compared: a PSI or a median over many rows
    identifies no one, and rare values are never printed (SMALL_COUNT).
    """
    pii = c.get("pii") or ""
    return not ((pii and not pii.startswith("quasi")) or c.get("key_candidate")
                or _io.KEY_NAME_HINTS.search(c["name"])
                or c.get("inferred_type") in ("free text", "identifier-like text"))


def psi(base, cur):
    """Population stability index over aligned count lists."""
    nb, nc = sum(base) or 1, sum(cur) or 1
    total = 0.0
    for b, c in zip(base, cur):
        pb, pc = max(b / nb, PSI_EPS), max(c / nc, PSI_EPS)
        total += (pc - pb) * math.log(pc / pb)
    return total


def psi_severity(v):
    return "major" if v >= PSI_MAJOR else "moderate" if v >= PSI_MODERATE else "stable"


def unit_hint(m_base, m_cur):
    if not m_base or not m_cur or (m_base > 0) != (m_cur > 0):
        return None
    k = round(math.log10(abs(m_cur / m_base)))
    if k and abs(m_cur / m_base / 10 ** k - 1) <= 0.10:
        return f"median moved x10^{k} (x{10 ** k:g}): possible unit change"
    return None


def value_sql(c: dict) -> str:
    x = q(c["name"])
    return f"CAST({x} AS DOUBLE)" if c["kind"] == "numeric" else P.num_expr(f"CAST({x} AS VARCHAR)")


def compare(base_path, cur_path, columns=None, bins=10, allow_download=False) -> dict:
    pb = P.profile(base_path, allow_download=allow_download)
    pc = P.profile(cur_path, allow_download=allow_download)
    for p in (pb, pc):
        if p.get("error"):
            return p
    con = _io.connect()
    _io.create_view(con, _io.open_source(base_path), allow_download, name="b")
    _io.create_view(con, _io.open_source(cur_path), allow_download, name="c")
    nb, nc = pb["rows"], pc["rows"]
    cb = {c["name"]: c for c in pb["columns"]}
    cc = {c["name"]: c for c in pc["columns"]}
    problems = []
    if columns:
        unknown = [c for c in columns if c not in cb and c not in cc]
        problems += [f"--columns names '{c}', which is in neither file" for c in unknown]

    removed = [n for n in cb if n not in cc]
    added = [n for n in cc if n not in cb]
    schema = [{"column": n, "change": "removed", "breaking": True} for n in removed]
    schema += [{"column": n, "change": "added", "breaking": False} for n in added]
    if not nb:
        problems.append("the baseline has 0 rows: there is nothing to compare against")
    for n in cb:
        if n in cc and "unknown" in (family(cb[n]), family(cc[n])) and family(cb[n]) != family(cc[n]):
            problems.append(f"{n}: no values on one side, so its type cannot be compared")
        elif n in cc and family(cb[n]) != family(cc[n]):
            schema.append({"column": n, "change": f"type {family(cb[n])} → {family(cc[n])}", "breaking": True,
                           "detail": f"{cb[n].get('inferred_type', cb[n]['duckdb_type'])} → "
                                     f"{cc[n].get('inferred_type', cc[n]['duckdb_type'])}"})
    renames = []
    for r in removed:
        for a in added:
            x, y = cb[r], cc[a]
            dx = x["distinct"] / (x["present"] or 1)
            dy = y["distinct"] / (y["present"] or 1)
            if family(x) == family(y) and abs(missing(x) / (nb or 1) - missing(y) / (nc or 1)) < 0.02 \
                    and abs(dx - dy) <= 0.10 * max(dx, dy, 1e-9):
                renames.append({"from": r, "to": a})

    drift = []
    for n, b in cb.items():
        if n not in cc or (columns and n not in columns) or family(b) != family(cc[n]):
            continue
        c = cc[n]
        mb, mc = missing(b) / (nb or 1), missing(c) / (nc or 1)
        pool = (missing(b) + missing(c)) / ((nb + nc) or 1)
        se = math.sqrt(pool * (1 - pool) * (1 / (nb or 1) + 1 / (nc or 1)))
        z = (mc - mb) / se if se else (0.0 if mc == mb else math.inf)
        d = abs(mc - mb)
        miss_sev = "major" if abs(z) >= 3 and d >= 0.10 else "moderate" if abs(z) >= 3 and d >= 0.01 else "stable"
        rec = {"column": n, "family": family(b), "missing_base": mb, "missing_cur": mc, "missing_z": z,
               "missing_severity": miss_sev, "psi": None, "psi_severity": None, "notes": []}
        fam = family(b)
        if not comparable_values(b) or not comparable_values(c):
            rec["notes"].append("identifier, personal data or free text: values not compared")
            rec["distinct_ratio"] = [b["distinct"] / (b["present"] or 1), c["distinct"] / (c["present"] or 1)]
        elif fam == "number":
            numeric_drift(con, b, c, bins, rec)
        elif fam == "text" and b["distinct"] <= CATEGORY_MAX:
            category_drift(con, b, c, rec)
        else:
            rec["notes"].append(f"{fam} column: compared by missing share only")
        sevs = [rec["missing_severity"]] + ([rec["psi_severity"]] if rec["psi_severity"] else [])
        rec["severity"] = max(sevs, key=RANK.get)
        drift.append(rec)

    cov_b = _io.coverage_for(_io.open_source(base_path), nb, nb)
    cov_c = _io.coverage_for(_io.open_source(cur_path), nc, nc)
    worst = max([r["severity"] for r in drift] or ["stable"], key=RANK.get)
    return {"baseline": {"path": base_path, "rows": nb}, "current": {"path": cur_path, "rows": nc},
            "schema": schema, "possible_renames": renames, "drift": drift, "worst": worst,
            "breaking": any(s["breaking"] for s in schema), "problems": problems,
            "coverage": {"baseline": cov_b, "current": cov_c}}


def numeric_drift(con, b, c, bins, rec):
    vb, vc = value_sql(b), value_sql(c)
    qs = [i / bins for i in range(1, bins)]
    edges = con.execute(f"SELECT quantile_cont({vb}, {qs}) FROM b WHERE {vb} IS NOT NULL").fetchone()[0] or []
    edges = sorted(set(edges))
    case = "CASE " + " ".join(f"WHEN v <= {e!r} THEN {i}" for i, e in enumerate(edges)) + f" ELSE {len(edges)} END" \
        if edges else "0"

    def side(view, v):
        stats = con.execute(f"SELECT count(v), avg(v), median(v), quantile_cont(v, 0.95), stddev_samp(v) "
                            f"FROM (SELECT {v} v FROM {view}) WHERE v IS NOT NULL").fetchone()
        counts = dict(con.execute(f"SELECT {case} k, count(*) FROM (SELECT {v} v FROM {view}) "
                                  f"WHERE v IS NOT NULL GROUP BY 1").fetchall())
        return stats, [counts.get(i, 0) for i in range(len(edges) + 1)]

    (nb_, mean_b, med_b, p95_b, sd_b), hb = side("b", vb)
    (nc_, mean_c, med_c, p95_c, sd_c), hc = side("c", vc)
    rec.update({"values": [nb_, nc_], "mean": [mean_b, mean_c], "median": [med_b, med_c],
                "p95": [p95_b, p95_c], "bins": len(hb)})
    if nb_ and nc_:
        rec["psi"] = psi(hb, hc)
        rec["psi_severity"] = psi_severity(rec["psi"])
        hint = unit_hint(med_b, med_c)
        if hint:
            rec["notes"].append(hint)
        # PSI over deciles can miss a few extreme values (a 4% slice at x100); the mean cannot
        se = math.sqrt((sd_b or 0) ** 2 / nb_ + (sd_c or 0) ** 2 / nc_) if nb_ > 1 and nc_ > 1 else 0
        rel = abs(mean_c - mean_b) / abs(mean_b) if mean_b else 0
        if se and abs(mean_c - mean_b) / se >= 3 and rel >= MEAN_MODERATE:
            sev = "major" if rel >= MEAN_MAJOR else "moderate"
            if RANK[sev] > RANK[rec["psi_severity"]]:
                rec["psi_severity"] = sev
                rec["notes"].append(f"mean moved {100 * (mean_c - mean_b) / abs(mean_b):+.0f}% "
                                    f"(z {(mean_c - mean_b) / se:+.1f}) while the deciles held: the change is "
                                    "in the tail (outliers or a small subset); find when with anomaly_detection.py")
    if min(nb_, nc_) < LOW_SAMPLE:
        rec["notes"].append(f"fewer than {LOW_SAMPLE} values on one side: PSI is unreliable")


def category_drift(con, b, c, rec):
    x = q(b["name"])
    norm = f"trim(CAST({x} AS VARCHAR))"
    ph = ", ".join(lit(p) for p in _io.PLACEHOLDERS)
    where = f"{x} IS NOT NULL AND {norm} <> '' AND lower({norm}) NOT IN ({ph})"
    base = dict(con.execute(f"SELECT {norm}, count(*) FROM b WHERE {where} GROUP BY 1").fetchall())
    cur = dict(con.execute(f"SELECT {norm}, count(*) FROM c WHERE {where} GROUP BY 1").fetchall())
    cats = sorted(base)
    new = {k: v for k, v in cur.items() if k not in base}
    hb = [base[k] for k in cats] + [0]
    hc = [cur.get(k, 0) for k in cats] + [sum(new.values())]
    tb, tc = sum(hb) or 1, sum(hc) or 1
    rec["psi"] = psi(hb, hc)
    rec["psi_severity"] = psi_severity(rec["psi"])
    rec["values"] = [sum(hb), sum(hc)]
    # a value seen fewer than SMALL_COUNT times can single a person out: count it, never name it
    nameable = lambda k: max(base.get(k, 0), cur.get(k, 0)) >= P.SMALL_COUNT  # noqa: E731
    moves = sorted(({"value": k, "share_base": base[k] / tb, "share_cur": cur.get(k, 0) / tc}
                    for k in cats if nameable(k)), key=lambda m: -abs(m["share_cur"] - m["share_base"]))
    rec["movers"] = moves[:5]
    rec["vanished"] = [k for k in cats if k not in cur and nameable(k)]
    rec["new_values"] = {"distinct": len(new), "share": sum(new.values()) / tc,
                         "values": [k for k in sorted(new, key=new.get, reverse=True) if nameable(k)][:5]}
    if min(sum(hb), sum(hc)) < LOW_SAMPLE:
        rec["notes"].append(f"fewer than {LOW_SAMPLE} values on one side: PSI is unreliable")


def render(r) -> str:
    b, c = r["baseline"], r["current"]
    L = [f"DRIFT CHECK  baseline {b['path']}  →  current {c['path']}",
         f"rows {b['rows']:,} → {c['rows']:,} ({_io.pct(c['rows'] - b['rows'], b['rows'])} change)", "",
         "SCHEMA"]
    if not r["schema"]:
        L.append("  no changes")
    for s in r["schema"]:
        tag = "BREAKING" if s["breaking"] else "additive"
        L.append(f"  {tag:<9} {s['column']:<24} {s['change']}" + (f"  ({s['detail']})" if s.get("detail") else ""))
    for m in r["possible_renames"]:
        L.append(f"  possible rename: {m['from']} → {m['to']} (same type, missing share and distinct ratio; verify)")
    L += ["", "DRIFT  (PSI < 0.10 stable · 0.10–0.25 moderate · ≥ 0.25 major)"]
    for d in sorted(r["drift"], key=lambda d: (-RANK[d["severity"]], d["column"])):
        psi_s = f"PSI {d['psi']:.3f}" if d["psi"] is not None else "PSI   n/a"
        L.append(f"  {d['severity'].upper():<9} {d['column']:<22} {psi_s:<11} missing "
                 f"{100 * d['missing_base']:.1f}% → {100 * d['missing_cur']:.1f}%"
                 + (f" (z {d['missing_z']:+.1f})" if d["missing_severity"] != "stable" else ""))
        if d.get("median"):
            L.append(f"            median {d['median'][0]:,.2f} → {d['median'][1]:,.2f} · mean "
                     f"{d['mean'][0]:,.2f} → {d['mean'][1]:,.2f} · p95 {d['p95'][0]:,.2f} → {d['p95'][1]:,.2f}")
        if d.get("movers") and d["psi_severity"] != "stable":
            L.append("            " + " · ".join(f"{m['value']} {100 * m['share_base']:.0f}% → "
                                              f"{100 * m['share_cur']:.0f}%" for m in d["movers"][:3]))
        if d.get("vanished"):
            L.append(f"            gone from current: {', '.join(d['vanished'][:5])}")
        nv = d.get("new_values")
        if nv and nv["distinct"]:
            L.append(f"            new in current: {nv['distinct']} value(s), {100 * nv['share']:.1f}% of rows"
                     + (f" ({', '.join(nv['values'])})" if nv["values"] else " (each too rare to name)"))
        for n in d["notes"]:
            L.append(f"            {n}")
    L += ["", f"WORST DRIFT: {r['worst']}" + (" · BREAKING SCHEMA CHANGE" if r["breaking"] else ""),
          "Drift is an OBSERVATION: it says the data changed, not why (references/data-drift.md)."]
    if r["problems"]:
        L += ["", "PROBLEMS"] + [f"  - {p}" for p in r["problems"]]
    L += ["", "baseline " + r["coverage"]["baseline"].line(), "current  " + r["coverage"]["current"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline")
    ap.add_argument("current")
    ap.add_argument("--columns", default="")
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--fail-on", choices=["moderate", "major"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    if a.bins < 2:
        print("--bins must be at least 2", file=sys.stderr)
        return _io.EXIT_USAGE
    cols = [c.strip() for c in a.columns.split(",") if c.strip()]
    r = compare(a.baseline, a.current, cols, a.bins, a.allow_extension_download)
    if r.get("error"):
        print(r.get("message", r["error"]), file=sys.stderr)
        return _io.EXIT_EXTENSION_REQUIRED if r["error"] == "extension_required" else _io.EXIT_USAGE
    if a.json:
        _io.emit_json(r)
    else:
        print(render(r))
    if a.fail_on and (r["breaking"] or RANK[r["worst"]] >= RANK[a.fail_on]):
        return _io.EXIT_FINDINGS
    return 0


if __name__ == "__main__":
    sys.exit(main())
