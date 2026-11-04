#!/usr/bin/env python3
"""Find exact duplicate rows and duplicate business keys.

    python3 detect_duplicates.py <path> [--key col[,col]] [--normalize]
                                 [--order-by col] [--show-keys] [--json]

--key        business key; without it only exact duplicate rows are checked
--normalize  compare keys after lower(trim()) — catches 'A1 ' vs 'a1'
--order-by   emit (never run) SQL that keeps the latest row per key
--show-keys  list the most repeated key values (refused for identifier columns)

Nothing is modified. Any dedupe SQL is printed for review, and it writes to a
NEW file so the original stays as it is.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
from _common import lit, q  # noqa: E402


def analyse(path, key=None, normalize=False, order_by=None, show_keys=False,
            sheet=None, allow_download=False) -> dict:
    con = _io.connect()
    src = _io.open_source(path, sheet=sheet)
    try:
        cols = _io.create_view(con, src, allow_download)
    except _io.ExtensionRequired as e:
        return {"error": "extension_required", "message": str(e)}
    names = [c for c, _ in cols]
    rows = con.execute("SELECT count(*) FROM src").fetchone()[0]
    allcols = ", ".join(q(c) for c in names)

    groups, rows_in, extra = con.execute(
        f"SELECT count(*), coalesce(sum(n), 0), coalesce(sum(n - 1), 0) FROM "
        f"(SELECT count(*) AS n FROM src GROUP BY {allcols} HAVING count(*) > 1)").fetchone()
    out = {"rows": rows, "exact": {"groups": groups, "rows_in_groups": rows_in, "extra_copies": extra}}

    if key:
        kcols = [k.strip() for k in key.split(",") if k.strip()]
        missing = [k for k in kcols if k not in names]
        if missing:
            return {"error": "unknown_key", "message": f"key column(s) not in data: {', '.join(missing)}. "
                                                       f"Columns: {', '.join(names)}"}
        kexpr = [f"lower(trim(CAST({q(k)} AS VARCHAR)))" if normalize else q(k) for k in kcols]
        knull = " OR ".join(f"{q(k)} IS NULL" for k in kcols)
        null_keys = con.execute(f"SELECT count(*) FROM src WHERE {knull}").fetchone()[0]
        g, r_in, ex, conflicting = con.execute(
            f"SELECT count(*), coalesce(sum(n), 0), coalesce(sum(n - 1), 0), "
            f"count(*) FILTER (WHERE versions > 1) FROM "
            f"(SELECT count(*) AS n, count(DISTINCT hash({allcols})) AS versions "
            f" FROM src WHERE NOT ({knull}) GROUP BY {', '.join(kexpr)} HAVING count(*) > 1)").fetchone()
        out["key"] = {"columns": kcols, "normalized": normalize, "null_keys": null_keys,
                      "duplicate_keys": g, "rows_in_groups": r_in, "extra_rows": ex,
                      "keys_with_conflicting_versions": conflicting,
                      "keys_that_are_pure_copies": g - conflicting}
        identifier = any(_io.PII_NAME_HINTS.search(k) for k in kcols)
        if show_keys and identifier:
            out["key"]["top_keys"] = "refused: key is an identifier column (rule 4)"
        elif show_keys:
            out["key"]["top_keys"] = con.execute(
                f"SELECT {', '.join(kexpr)}, count(*) n FROM src WHERE NOT ({knull}) "
                f"GROUP BY ALL HAVING count(*) > 1 ORDER BY n DESC LIMIT 10").fetchall()
        if order_by:
            if order_by not in names:
                return {"error": "unknown_column", "message": f"--order-by column not in data: {order_by}"}
            part = ", ".join(q(k) for k in kcols)
            rel = _io.relation_sql(src)
            dest = os.path.splitext(src.files[0])[0] + ".dedup.csv"
            out["dedupe_sql"] = (
                "-- Keeps the latest row per key. Writes a NEW file; the original is untouched.\n"
                f"-- Expected impact: removes {ex:,} rows ({_io.pct(ex, rows)}), keeps {rows - ex:,}.\n"
                f"-- Rows with a NULL key ({null_keys:,}) are kept as they are.\n"
                f"COPY (\n  SELECT * FROM {rel}\n"
                f"  QUALIFY {knull} OR row_number() OVER (\n"
                f"    PARTITION BY {part}\n"
                f"    ORDER BY TRY_CAST({q(order_by)} AS TIMESTAMP) DESC NULLS LAST) = 1\n"
                f") TO {lit(dest)} (HEADER);")
    out["coverage"] = _io.coverage_for(src, rows, rows)
    return out


def render(r: dict) -> str:
    rows, e = r["rows"], r["exact"]
    L = [f"ROWS  {rows:,}", "",
         f"EXACT DUPLICATE ROWS  {e['extra_copies']:,} extra copies ({_io.pct(e['extra_copies'], rows)}) "
         f"in {e['groups']:,} groups"]
    if "key" in r:
        k = r["key"]
        L += ["", f"KEY  ({', '.join(k['columns'])}{', normalized lower(trim())' if k['normalized'] else ''})",
              f"  duplicate keys        {k['duplicate_keys']:,}",
              f"  extra rows            {k['extra_rows']:,} ({_io.pct(k['extra_rows'], rows)})",
              f"  pure copies           {k['keys_that_are_pure_copies']:,} keys  (every row identical — safe to drop)",
              f"  conflicting versions  {k['keys_with_conflicting_versions']:,} keys  "
              "(same key, different values — you must choose a winner)",
              f"  null keys             {k['null_keys']:,}"]
        if isinstance(k.get("top_keys"), str):
            L.append(f"  top keys              {k['top_keys']}")
        elif k.get("top_keys"):
            L.append("  top keys              " + ", ".join(
                f"{'|'.join(str(v) for v in t[:-1])}×{t[-1]}" for t in k["top_keys"]))
    if r.get("dedupe_sql"):
        L += ["", "PROPOSED DEDUPE (not run — review, then execute yourself)", r["dedupe_sql"]]
    L += ["", r["coverage"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--key")
    ap.add_argument("--normalize", action="store_true")
    ap.add_argument("--order-by")
    ap.add_argument("--show-keys", action="store_true")
    ap.add_argument("--sheet")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    r = analyse(a.path, a.key, a.normalize, a.order_by, a.show_keys, a.sheet, a.allow_extension_download)
    if "error" in r:
        print("ERROR: " + r["message"], file=sys.stderr)
        return _io.EXIT_EXTENSION_REQUIRED if r["error"] == "extension_required" else _io.EXIT_USAGE
    if a.json:
        _io.emit_json(r)
    else:
        print(render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
