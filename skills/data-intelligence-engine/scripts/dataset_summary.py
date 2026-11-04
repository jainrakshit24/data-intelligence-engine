#!/usr/bin/env python3
"""One-screen first look at a dataset: shape, columns and missingness, in one scan.

    python3 dataset_summary.py <path> [--sheet NAME] [--json] [--allow-extension-download]

Cheaper than profile_dataset.py. Use it to decide what to look at next; it
draws no conclusions about types, quality or PII.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
from _common import q  # noqa: E402


def summarize(path, sheet=None, allow_download=False) -> dict:
    con = _io.connect()
    src = _io.open_source(path, sheet=sheet)
    try:
        cols = _io.create_view(con, src, allow_download)
    except _io.ExtensionRequired as e:
        return {"error": "extension_required", "message": str(e),
                "sheets": src.sheets, "sheet_rows": src.sheet_rows}
    exprs = ["count(*)"] + [f"count({q(n)})" for n, _ in cols]
    row = con.execute("SELECT " + ", ".join(exprs) + " FROM src").fetchone()
    rows = row[0]
    columns = [{"name": n, "duckdb_type": t, "missing": rows - nn} for (n, t), nn in zip(cols, row[1:])]
    return {"source": {"path": src.path, "format": src.fmt, "bytes": src.bytes,
                       "sheets": src.sheets, "sheet": src.sheet},
            "rows": rows, "columns": columns, "coverage": _io.coverage_for(src, rows, rows)}


def render(s) -> str:
    src, rows = s["source"], s["rows"]
    L = [f"{src['path']}  ·  {src['format']}  ·  {src['bytes'] / 1024:,.0f} KiB  ·  "
         f"{rows:,} rows × {len(s['columns'])} columns"]
    if src["sheets"]:
        L.append(f"sheets: {', '.join(src['sheets'])}  (read: {src['sheet']})")
    L.append("")
    for c in s["columns"]:
        miss = f"{_io.pct(c['missing'], rows)} missing" if c["missing"] else ""
        L.append(f"  {c['name']:<28} {c['duckdb_type'].lower():<10} {miss}")
    L += ["", "types shown are as read (CSV is read as text on purpose); run profile_dataset.py for "
              "inferred types, quality and PII.", "", s["coverage"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--sheet")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    s = summarize(a.path, a.sheet, a.allow_extension_download)
    if s.get("error"):
        print(s["message"], file=sys.stderr)
        if s.get("sheets"):
            print(_io.sheets_line(s["sheets"], s["sheet_rows"]), file=sys.stderr)
        return _io.EXIT_EXTENSION_REQUIRED
    if a.json:
        _io.emit_json(s)
    else:
        print(render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
