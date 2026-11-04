#!/usr/bin/env python3
"""Reconcile a pipeline's input against its output: account for every row.

    python3 reconcile.py <source> <target> --key col[,col] [--compare col,..|all]
                         [--sum col,..] [--normalize-keys] [--tolerance 1e-9] [--json]

For two datasets that should describe the same things (a staging table and
the warehouse table built from it, yesterday's and today's extract, the
input and output of a transformation), it reports:

  ROW ACCOUNTING  target rows = source rows − dropped + added − collapsed
                  + fanned out − null keys(source) + null keys(target), exactly
  VALUE CHANGES   per column, for keys that occur once on each side
  SUM DELTAS      each --sum column's total delta split into dropped, added,
                  changed and duplicate contributions
  SCHEMA          columns only on one side

Key values are identifiers and are never printed. To inspect them, run the
SQL this script prints (it writes a NEW file; it is never run for you).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
from _common import lit, q  # noqa: E402
from profile_dataset import num_expr  # noqa: E402

SEP = "chr(31)"


def key_expr(cols, normalize):
    parts = [f"lower(trim(CAST({q(c)} AS VARCHAR)))" if normalize else f"CAST({q(c)} AS VARCHAR)"
             for c in cols]
    return parts[0] if len(parts) == 1 else f"concat_ws({SEP}, {', '.join(parts)})"


def reconcile(source, target, key, compare=None, sums=None, normalize=False, tolerance=1e-9,
              allow_download=False) -> dict:
    con = _io.connect()
    s_src, t_src = _io.open_source(source), _io.open_source(target)
    try:
        s_cols = dict(_io.create_view(con, s_src, allow_download, name="s"))
        t_cols = dict(_io.create_view(con, t_src, allow_download, name="t"))
    except _io.ExtensionRequired as e:
        return {"error": "extension_required", "message": str(e)}
    kcols = [k.strip() for k in key.split(",") if k.strip()]
    missing = [f"{k} (source)" for k in kcols if k not in s_cols] + \
              [f"{k} (target)" for k in kcols if k not in t_cols]
    if missing:
        return {"error": "unknown_key", "message": "key column(s) missing: " + ", ".join(missing)}
    shared = [c for c in s_cols if c in t_cols]
    if compare == "all" or compare is None:
        cmp_cols = [c for c in shared if c not in kcols] if compare == "all" else []
    else:
        cmp_cols = [c.strip() for c in compare.split(",") if c.strip()]
    sum_cols = [c.strip() for c in (sums or "").split(",") if c.strip()]
    problems = [f"column '{c}' is not on both sides; skipped" for c in cmp_cols + sum_cols if c not in shared]
    cmp_cols = [c for c in cmp_cols if c in shared]
    sum_cols = [c for c in sum_cols if c in shared]

    kx = key_expr(kcols, normalize)
    knull = " OR ".join(f"{q(k)} IS NULL" for k in kcols)
    for side in ("s", "t"):
        con.execute(f"CREATE TEMP TABLE k{side} AS SELECT {kx} AS k, count(*) AS n FROM {side} "
                    f"WHERE NOT ({knull}) GROUP BY 1")
    rows_s, null_s = con.execute(f"SELECT count(*), count(*) FILTER (WHERE {knull}) FROM s").fetchone()
    rows_t, null_t = con.execute(f"SELECT count(*), count(*) FILTER (WHERE {knull}) FROM t").fetchone()
    acc = con.execute("""
        SELECT
          count(*) FILTER (WHERE kt.k IS NULL),               coalesce(sum(ks.n) FILTER (WHERE kt.k IS NULL), 0),
          count(*) FILTER (WHERE ks.k IS NULL),               coalesce(sum(kt.n) FILTER (WHERE ks.k IS NULL), 0),
          count(*) FILTER (WHERE ks.k IS NOT NULL AND kt.k IS NOT NULL),
          coalesce(sum(ks.n - kt.n) FILTER (WHERE ks.n > kt.n), 0),
          count(*) FILTER (WHERE ks.n > kt.n),
          coalesce(sum(kt.n - ks.n) FILTER (WHERE kt.n > ks.n), 0),
          count(*) FILTER (WHERE kt.n > ks.n),
          count(*) FILTER (WHERE ks.n = 1 AND kt.n = 1)
        FROM ks FULL OUTER JOIN kt USING (k)""").fetchone()
    (dropped_keys, dropped_rows, added_keys, added_rows, matched_keys,
     collapsed_rows, collapsed_keys, fanned_rows, fanned_keys, comparable) = acc
    explained = (rows_s - null_s - dropped_rows + added_rows - collapsed_rows + fanned_rows + null_t)
    accounting = {
        "source_rows": rows_s, "target_rows": rows_t,
        "null_key_rows_source": null_s, "null_key_rows_target": null_t,
        "dropped_keys": dropped_keys, "dropped_rows": dropped_rows,
        "added_keys": added_keys, "added_rows": added_rows,
        "matched_keys": matched_keys,
        "collapsed_keys": collapsed_keys, "collapsed_rows": collapsed_rows,
        "fanned_out_keys": fanned_keys, "fanned_out_rows": fanned_rows,
        "unexplained_rows": rows_t - explained,
    }

    # ---- value changes: only keys that occur exactly once on each side ----
    changes = []
    if cmp_cols:
        con.execute(f"""CREATE TEMP TABLE pair AS
            SELECT {', '.join(f's.{q(c)} AS {q("s_" + c)}, t.{q(c)} AS {q("t_" + c)}' for c in cmp_cols)}
            FROM (SELECT *, {kx} AS _k FROM s) s JOIN (SELECT *, {kx} AS _k FROM t) t USING (_k)
            WHERE _k IN (SELECT k FROM ks WHERE n = 1) AND _k IN (SELECT k FROM kt WHERE n = 1)""")
        for c in cmp_cols:
            a, b = q("s_" + c), q("t_" + c)
            na, nb = num_expr(f"CAST({a} AS VARCHAR)"), num_expr(f"CAST({b} AS VARCHAR)")
            differs = (f"CASE WHEN {na} IS NOT NULL AND {nb} IS NOT NULL THEN abs({na} - {nb}) > {float(tolerance)} "
                       f"ELSE trim(CAST({a} AS VARCHAR)) IS DISTINCT FROM trim(CAST({b} AS VARCHAR)) END")
            changed, lost, gained = con.execute(
                f"SELECT count(*) FILTER (WHERE {differs}), "
                f"count(*) FILTER (WHERE {a} IS NOT NULL AND {b} IS NULL), "
                f"count(*) FILTER (WHERE {a} IS NULL AND {b} IS NOT NULL) FROM pair").fetchone()
            changes.append({"column": c, "changed": changed, "became_null": lost,
                            "became_non_null": gained, "compared": comparable})

    # ---- sum deltas, split by cause ----
    sum_out = []
    for c in sum_cols:
        ns, nt = num_expr(f"CAST(s.{q(c)} AS VARCHAR)"), num_expr(f"CAST(t.{q(c)} AS VARCHAR)")
        tot_s, unparsed_s = con.execute(f"SELECT sum({ns}), count(s.{q(c)}) - count({ns}) FROM s").fetchone()
        tot_t, unparsed_t = con.execute(f"SELECT sum({nt}), count(t.{q(c)}) - count({nt}) FROM t").fetchone()
        part = {}
        for side, ex in (("s", ns), ("t", nt)):
            part[side] = dict(zip(
                ("null_key", "unmatched", "single", "multi"),
                con.execute(f"""
                    WITH x AS (SELECT {kx} AS _k, {ex} AS v, ({knull}) AS nk FROM {side} {side})
                    SELECT coalesce(sum(v) FILTER (WHERE nk), 0),
                           coalesce(sum(v) FILTER (WHERE NOT nk AND _k NOT IN (SELECT k FROM k{'t' if side == 's' else 's'})), 0),
                           coalesce(sum(v) FILTER (WHERE NOT nk AND _k IN (SELECT k FROM ks WHERE n = 1)
                                                       AND _k IN (SELECT k FROM kt WHERE n = 1)), 0),
                           coalesce(sum(v) FILTER (WHERE NOT nk AND _k IN (SELECT k FROM ks JOIN kt USING (k)
                                                                         WHERE ks.n > 1 OR kt.n > 1)), 0)
                    FROM x""").fetchone()))
        tot_s, tot_t = float(tot_s or 0), float(tot_t or 0)
        contrib = {
            "dropped": -float(part["s"]["unmatched"]),
            "added": float(part["t"]["unmatched"]),
            "changed_values": float(part["t"]["single"]) - float(part["s"]["single"]),
            "duplicate_keys": float(part["t"]["multi"]) - float(part["s"]["multi"]),
            "null_keys": float(part["t"]["null_key"]) - float(part["s"]["null_key"]),
        }
        contrib = {k: v + 0.0 for k, v in contrib.items()}  # no "-0.00" in the report
        sum_out.append({"column": c, "source_total": tot_s, "target_total": tot_t, "delta": tot_t - tot_s,
                        "contributions": contrib,
                        "unexplained": (tot_t - tot_s) - sum(contrib.values()),
                        "unparsed_source": unparsed_s, "unparsed_target": unparsed_t})

    cov_s = _io.coverage_for(s_src, rows_s, rows_s)
    cov_t = _io.coverage_for(t_src, rows_t, rows_t)
    out_dir = os.path.dirname(os.path.abspath(target))
    dropped_sql = (f"COPY (SELECT DISTINCT {kx} AS key FROM {_io.relation_sql(s_src)} "
                   f"WHERE NOT ({knull}) AND {kx} NOT IN (SELECT {kx} FROM {_io.relation_sql(t_src)} "
                   f"WHERE NOT ({knull}))) TO {lit(os.path.join(out_dir, 'dropped_keys.csv'))} (HEADER);")
    return {"source": {"path": s_src.path, "format": s_src.fmt}, "target": {"path": t_src.path, "format": t_src.fmt},
            "key": kcols, "normalized": normalize, "accounting": accounting, "changes": changes, "sums": sum_out,
            "schema": {"only_in_source": [c for c in s_cols if c not in t_cols],
                       "only_in_target": [c for c in t_cols if c not in s_cols],
                       "type_changed": [{"column": c, "source": s_cols[c], "target": t_cols[c]}
                                        for c in shared if s_cols[c] != t_cols[c]]},
            "problems": problems, "dropped_keys_sql": dropped_sql,
            "coverage": {"source": cov_s, "target": cov_t}}


def fmt(x):
    return f"{x:,.2f}" if isinstance(x, float) else f"{x:,}"


def render(r) -> str:
    a = r["accounting"]
    pct = lambda n: _io.pct(n, a["source_rows"])  # noqa: E731
    L = [f"RECONCILE  {r['source']['path']}  →  {r['target']['path']}",
         f"key: {', '.join(r['key'])}" + ("  (compared after lower(trim()))" if r["normalized"] else ""), "",
         "ROW ACCOUNTING  (every target row explained from the source)",
         f"  source rows                         {a['source_rows']:>12,}",
         f"  − rows whose key is not in target   {a['dropped_rows']:>12,}   ({a['dropped_keys']:,} keys, {pct(a['dropped_rows'])})",
         f"  + rows whose key is new in target   {a['added_rows']:>12,}   ({a['added_keys']:,} keys)",
         f"  − duplicate rows collapsed          {a['collapsed_rows']:>12,}   ({a['collapsed_keys']:,} keys)",
         f"  + rows fanned out (key multiplied)  {a['fanned_out_rows']:>12,}   ({a['fanned_out_keys']:,} keys)",
         f"  − null-key rows in source           {a['null_key_rows_source']:>12,}",
         f"  + null-key rows in target           {a['null_key_rows_target']:>12,}",
         f"  = target rows                       {a['target_rows']:>12,}"
         + ("   ✓ fully explained" if a["unexplained_rows"] == 0 else f"   ✗ {a['unexplained_rows']:,} UNEXPLAINED")]
    if a["fanned_out_rows"]:
        L.append("  ! fan-out: keys appear more often in the target than in the source — typical of a join on a "
                 "non-unique key. Totals summed over the target will be inflated.")
    if r["changes"]:
        n = r["changes"][0]["compared"]
        L += ["", f"VALUE CHANGES  ({n:,} keys present exactly once on each side; numbers compared numerically)"]
        for c in r["changes"]:
            L.append(f"  {c['column']:<24} changed {c['changed']:>8,} ({_io.pct(c['changed'], n)})"
                     f"   became null {c['became_null']:,}   null→value {c['became_non_null']:,}")
    for s in r["sums"]:
        c = s["contributions"]
        L += ["", f"SUM  {s['column']}:  {fmt(s['source_total'])} → {fmt(s['target_total'])}   "
                  f"delta {s['delta']:+,.2f} ({_io.pct(abs(s['delta']), abs(s['source_total']) or 1)})",
              f"  from dropped keys       {c['dropped']:+,.2f}",
              f"  from new keys           {c['added']:+,.2f}",
              f"  from changed values     {c['changed_values']:+,.2f}",
              f"  from duplicate keys     {c['duplicate_keys']:+,.2f}",
              f"  from null-key rows      {c['null_keys']:+,.2f}",
              "  " + ("✓ delta fully explained" if abs(s["unexplained"]) < 1e-6 * max(1.0, abs(s["delta"]))
                     else f"✗ {s['unexplained']:+,.2f} unexplained")]
        if s["unparsed_source"] or s["unparsed_target"]:
            L.append(f"  not summed (not numbers): {s['unparsed_source']:,} source, {s['unparsed_target']:,} target values")
    sc = r["schema"]
    if sc["only_in_source"] or sc["only_in_target"] or sc["type_changed"]:
        L += ["", "SCHEMA"]
        if sc["only_in_source"]:
            L.append(f"  only in source: {', '.join(sc['only_in_source'])}")
        if sc["only_in_target"]:
            L.append(f"  only in target: {', '.join(sc['only_in_target'])}")
        for t in sc["type_changed"]:
            L.append(f"  type changed: {t['column']} {t['source']} → {t['target']}")
    if r["problems"]:
        L += ["", "PROBLEMS"] + [f"  - {p}" for p in r["problems"]]
    if r["accounting"]["dropped_keys"]:
        L += ["", "TO LIST THE DROPPED KEYS (not run — identifiers; writes a NEW file):", "  " + r["dropped_keys_sql"]]
    L += ["", "source " + r["coverage"]["source"].line(), "target " + r["coverage"]["target"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("--key", required=True)
    ap.add_argument("--compare", help="comma-separated columns, or 'all'")
    ap.add_argument("--sum", dest="sums")
    ap.add_argument("--normalize-keys", action="store_true")
    ap.add_argument("--tolerance", type=float, default=1e-9)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    r = reconcile(a.source, a.target, a.key, a.compare, a.sums, a.normalize_keys, a.tolerance,
                  a.allow_extension_download)
    if r.get("error"):
        print(r["message"], file=sys.stderr)
        return _io.EXIT_EXTENSION_REQUIRED if r["error"] == "extension_required" else _io.EXIT_USAGE
    if a.json:
        _io.emit_json(r)
    else:
        print(render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
