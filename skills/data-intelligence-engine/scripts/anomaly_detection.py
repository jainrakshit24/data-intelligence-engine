#!/usr/bin/env python3
"""Find volume, metric and null-rate anomalies in a dataset over time.

    python3 anomaly_detection.py <path> --time COL [--grain hour|day|week|month]
            [--metric COL[,COL]] [--nulls COL[,COL]] [--by COL]
            [--threshold 3.5] [--seasonal auto|none] [--complete-through YYYY-MM-DD]
            [--fail-on-anomaly] [--json]

The data is bucketed into periods (empty periods are kept as 0). Per period it
measures row count, the mean of each --metric and the missing share of each
--nulls column, then:

  SEASONALITY  day grain: weekday factors; hour grain: hour-of-day factors
               (median of the slot / overall median, needs 3+ values per slot).
               Applied to row counts only.
  LEVEL SHIFT  the single strongest change in level (each side > 5 periods;
               a newer step shows up as point anomalies until then):
               t = |mean after - mean before| / (sigma * sqrt(1/n1 + 1/n2)),
               sigma from first differences, so the shift itself does not
               inflate it. Reported when t >= 6 and the change is >= 5%.
  POINTS       robust z = (value - level) / sigma, where level is the median of
               the value's side of the shift and sigma = 1.4826 x MAD of the
               residuals, never below the period's own sampling noise (Poisson
               for counts, binomial for rates, sd/sqrt(n) for means).
               Flagged when |z| > threshold (3.5, Iglewicz-Hoaglin).
               Empty periods are always flagged as missing.
  BY           with --by, each shift and each count anomaly is split into the
               segments that moved.

Means and rates are not scored for a period with fewer than 30 rows. The last
period is treated as possibly incomplete unless --complete-through covers it.
An anomaly is an OBSERVATION about the data, never a cause.
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
from _common import lit, q  # noqa: E402
from profile_dataset import num_expr  # noqa: E402

GRAINS = ("hour", "day", "week", "month")
LABEL_FMT = {"hour": "%Y-%m-%d %H:00", "day": "%Y-%m-%d", "week": "wk %Y-%m-%d", "month": "%Y-%m"}
NUMERIC_TYPES = ("DOUBLE", "FLOAT", "REAL", "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT", "DECIMAL")
TEMPORAL_TYPES = ("DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ")
MIN_SEGMENT = 5          # periods on each side of a level shift
SHIFT_T = 6.0            # t statistic a level shift must reach
SHIFT_MIN_CHANGE = 0.05  # ... and its relative size
MIN_RATE_BASE = 30       # rows a period needs before its mean or rate is scored
MAX_SEGMENTS = 20        # --by values kept by volume; the rest become "(other)"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def time_expr(col: str, dtype: str) -> str:
    x = q(col)
    if dtype.split("(")[0].upper() in TEMPORAL_TYPES:
        return f"CAST({x} AS TIMESTAMP)"
    s = f"trim(CAST({x} AS VARCHAR))"
    parts = [f"TRY_CAST({s} AS TIMESTAMP)"] + [f"try_strptime({s}, {lit(f)})" for f in _io.DATE_FORMATS]
    return f"coalesce({', '.join(parts)})"


def missing_expr(col: str) -> str:
    s = f"lower(trim(CAST({q(col)} AS VARCHAR)))"
    ph = ", ".join(lit(p) for p in _io.PLACEHOLDERS)
    return f"({q(col)} IS NULL OR {s} = '' OR {s} IN ({ph}))"


def step(p: datetime, grain: str) -> datetime:
    if grain == "month":
        return datetime(p.year + p.month // 12, p.month % 12 + 1, 1)
    return p + {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(days=7)}[grain]


def label(p: datetime, grain: str) -> str:
    return p.strftime(LABEL_FMT[grain])


def robust_sigma(values):
    """1.4826 x MAD; falls back to 1.2533 x mean absolute deviation; None if every value is equal."""
    if len(values) < 2:
        return None
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    if mad > 0:
        return 1.4826 * mad
    mean_ad = sum(abs(v - med) for v in values) / len(values)
    return 1.2533 * mean_ad if mean_ad > 0 else None


def level_shift(y):
    """Strongest single change in level of y (None entries are not scored). Returns dict or None."""
    idx = [i for i, v in enumerate(y) if v is not None]
    vals = [y[i] for i in idx]
    n = len(vals)
    if n < 2 * MIN_SEGMENT:
        return None
    sigma = robust_sigma([b - a for a, b in zip(vals, vals[1:])])
    if not sigma:
        return None
    sigma /= math.sqrt(2)  # a difference of two values has twice the variance
    # clip to a rolling median, so a single spike or empty day cannot pose as a shift
    # while a real shift (which persists) is left intact
    clipped = []
    for i, v in enumerate(vals):
        local = statistics.median(vals[max(0, i - 3):i + 4])
        clipped.append(min(max(v, local - 3.5 * sigma), local + 3.5 * sigma))
    pre = [0.0]
    for v in clipped:
        pre.append(pre[-1] + v)
    best_t, best_k = 0.0, None
    for k in range(MIN_SEGMENT, n - MIN_SEGMENT + 1):
        m1, m2 = pre[k] / k, (pre[n] - pre[k]) / (n - k)
        t = abs(m2 - m1) / (sigma * math.sqrt(1 / k + 1 / (n - k)))
        if t > best_t:
            best_t, best_k = t, k
    # a maximum at the edge of the allowed range means the step may lie beyond it (only 1-4
    # periods old): its date would be wrong, so leave those periods to the point check
    if best_k is None or best_t < SHIFT_T or best_k in (MIN_SEGMENT, n - MIN_SEGMENT):
        return None
    before, after = statistics.median(vals[:best_k]), statistics.median(vals[best_k:])
    if not before or abs(after - before) / abs(before) < SHIFT_MIN_CHANGE:
        return None
    return {"t": best_t, "index": idx[best_k], "before": before, "after": after,
            "change": (after - before) / abs(before)}


def score_points(y, shift, floor=None):
    """Robust z per position against the median of its side of the shift.

    floor(i, level) gives the smallest sigma that position can have: the sampling noise of a
    count (Poisson), a rate (binomial) or a mean (sd/sqrt n). Without it, a series that is
    calmer than sampling noise would flag every small or partial period.
    """
    cut = shift["index"] if shift else len(y)
    sides = [[], []]
    for i, v in enumerate(y):
        if v is not None:
            sides[i >= cut].append(v)
    levels = [statistics.median(s) if s else None for s in sides]
    lvl = [levels[i >= cut] if v is not None else None for i, v in enumerate(y)]
    sigma = robust_sigma([v - lv for v, lv in zip(y, lvl) if v is not None])
    z = []
    for i, (v, lv) in enumerate(zip(y, lvl)):
        # an unscored position has no level, so its floor cannot be computed either
        if v is None:
            z.append(None)
            continue
        s_i = max(sigma or 0.0, floor(i, lv) if floor else 0.0)
        if s_i:
            z.append((v - lv) / s_i)
        else:
            z.append(0.0 if v == lv else math.copysign(math.inf, v - lv))
    return z, lvl, sigma


def seasonal_factors(periods, counts, grain, mode):
    if mode == "none" or grain not in ("day", "hour"):
        return None
    slot = (lambda p: p.weekday()) if grain == "day" else (lambda p: p.hour)
    groups = {}
    for p, c in zip(periods, counts):
        groups.setdefault(slot(p), []).append(c)
    overall = statistics.median(counts) if counts else 0
    nslots = 7 if grain == "day" else 24
    if not overall or len(groups) < nslots or min(len(v) for v in groups.values()) < 3:
        return None
    return {"slot_of": slot, "factors": {s: statistics.median(v) / overall for s, v in groups.items()},
            "kind": "weekday" if grain == "day" else "hour-of-day"}


def shown(s, mask_values):
    return _io.mask(s) if mask_values and s != "(other)" else s


def scan(path, time_col, grain="day", metrics=None, nulls=None, by=None, threshold=3.5,
         seasonal="auto", complete_through=None, allow_download=False) -> dict:
    con = _io.connect()
    src = _io.open_source(path)
    try:
        cols = dict(_io.create_view(con, src, allow_download))
    except _io.ExtensionRequired as e:
        return {"error": "extension_required", "message": str(e)}
    metrics, nulls = metrics or [], nulls or []
    unknown = [c for c in [time_col, *metrics, *nulls] + ([by] if by else []) if c not in cols]
    if unknown:
        return {"error": "unknown_column", "message": "column(s) not in the data: " + ", ".join(unknown)}

    sel = [f"{time_expr(time_col, cols[time_col])} AS _ts",
           f"({q(time_col)} IS NULL OR trim(CAST({q(time_col)} AS VARCHAR)) = '') AS _ts_empty"]
    for i, m in enumerate(metrics):
        x = q(m) if cols[m].split("(")[0].upper() in NUMERIC_TYPES else num_expr(f"CAST({q(m)} AS VARCHAR)")
        sel.append(f"CAST({x} AS DOUBLE) AS _m{i}")
    sel += [f"{missing_expr(c)} AS _n{i}" for i, c in enumerate(nulls)]
    sel.append(f"coalesce(CAST({q(by)} AS VARCHAR), '(null)') AS _seg" if by else "NULL AS _seg")
    con.execute(f"CREATE TEMP TABLE b AS SELECT {', '.join(sel)} FROM src")
    rows_total, raw_empty, unparsed = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE _ts_empty), "
        "count(*) FILTER (WHERE _ts IS NULL AND NOT _ts_empty) FROM b").fetchone()
    agg = ["count(*)"] + [f"sum(_m{i}), sum(_m{i} * _m{i}), count(_m{i})" for i in range(len(metrics))] + \
          [f"count(*) FILTER (WHERE _n{i})" for i in range(len(nulls))]
    res = con.execute(f"SELECT date_trunc({lit(grain)}, _ts) p, {', '.join(agg)} FROM b "
                      f"WHERE _ts IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()
    if not res:
        return {"error": "no_time", "message": f"no value of '{time_col}' could be read as a date or timestamp"}

    by_p = {r[0]: r[1:] for r in res}
    periods, p = [], res[0][0]
    while p <= res[-1][0]:
        periods.append(p)
        p = step(p, grain)
        if len(periods) > 20000:
            return {"error": "too_many_periods", "message": f"over 20,000 {grain} periods: use a coarser --grain"}
    counts = [by_p[p][0] if p in by_p else 0 for p in periods]
    notes = []

    # periods that end after --complete-through are still loading: not scored
    scored_n, incomplete = len(periods), None
    if complete_through:
        ct = datetime.combine(date.fromisoformat(complete_through), datetime.max.time())
        while scored_n and step(periods[scored_n - 1], grain) - timedelta(microseconds=1) > ct:
            scored_n -= 1
        if scored_n < len(periods):
            incomplete = {"periods": [label(p, grain) for p in periods[scored_n:]], "reason": "after --complete-through"}
    sp, sc = periods[:scored_n], counts[:scored_n]

    season = seasonal_factors(sp, sc, grain, seasonal)

    def factor(p):
        return season["factors"][season["slot_of"](p)] if season else 1.0

    if season and any(f == 0 for f in season["factors"].values()):
        notes.append("some slots usually have no rows; they are not scored")
    findings, shifts, series_out = [], [], []

    def run_series(name, kind, y, display, expected_of, floor):
        shift = level_shift(y)
        z, lvl, sigma = score_points(y, shift, floor)
        if shift:
            shifts.append({"series": name, "kind": kind, "from": label(sp[shift["index"]], grain),
                           "index": shift["index"], "before": shift["before"], "after": shift["after"],
                           "change": shift["change"], "t": shift["t"]})
        for i, zi in enumerate(z):
            if zi is None:
                continue
            missing = kind == "rows" and display[i] == 0
            if missing or abs(zi) > threshold:
                findings.append({"period": label(sp[i], grain), "index": i, "series": name, "kind": kind,
                                 "value": display[i], "expected": expected_of(i, lvl[i]),
                                 "z": None if math.isinf(zi) else zi, "direction": "high" if zi > 0 else "low",
                                 "type": "missing period" if missing else ("spike" if zi > 0 else "drop")})
        series_out.append({"series": name, "kind": kind, "noise_sigma": sigma, "level_shift": bool(shift)})

    run_series("rows", "rows", [c / factor(sp[i]) if factor(sp[i]) else None for i, c in enumerate(sc)], sc,
               lambda i, lv: lv * factor(sp[i]) if lv is not None else None,
               lambda i, lv: math.sqrt(max(lv * factor(sp[i]), 1.0)) / factor(sp[i]))
    for j, m in enumerate(metrics):
        y, se = [], []
        for p in sp:
            s, ss, n = by_p[p][1 + 3 * j:4 + 3 * j] if p in by_p else (None, None, 0)
            ok = n >= MIN_RATE_BASE
            y.append(s / n if ok else None)
            se.append(math.sqrt(max(ss / n - (s / n) ** 2, 0.0) * n / (n - 1) / n) if ok else 0.0)
        run_series(f"mean({m})", "metric", y, y, lambda i, lv: lv, lambda i, lv, se=se: se[i])
    base = 1 + 3 * len(metrics)
    for j, c in enumerate(nulls):
        n = [by_p[p][0] if p in by_p else 0 for p in sp]
        y = [by_p[p][base + j] / by_p[p][0] if p in by_p and by_p[p][0] >= MIN_RATE_BASE else None for p in sp]
        run_series(f"missing share({c})", "null_rate", y, y, lambda i, lv: lv,
                   lambda i, lv, n=n: math.sqrt(lv * (1 - lv) / n[i]) if n[i] else 0.0)
    empty = sum(1 for c in sc if c == 0)
    if sc and empty > 0.1 * len(sc):
        notes.append(f"{empty} of {len(sc)} periods are empty, and each is listed: if the data is sparse "
                     "rather than broken, use a coarser --grain")
    small = sum(1 for c in sc if 0 < c < MIN_RATE_BASE)
    if (metrics or nulls) and small:
        notes.append(f"{small} period(s) have fewer than {MIN_RATE_BASE} rows: their means and rates are not scored")

    # without a cutoff, a low last period may simply still be filling up
    if not complete_through and sp:
        last = label(sp[-1], grain)
        for f in findings:
            if f["period"] == last and f["kind"] == "rows" and f["direction"] == "low":
                f["type"] = "low, but the last period may be incomplete"
        notes.append(f"last period {last} is scored as complete; pass --complete-through if it is still loading")

    if by:
        split_by_segment(con, by, grain, sp, sc, shifts, findings, notes)

    findings.sort(key=lambda f: (f["index"], f["series"]))
    cov = _io.coverage_for(src, rows_total, rows_total)
    if unparsed:
        cov.filters.append(f"{unparsed:,} rows whose {time_col} could not be read as a date/time excluded")
    if raw_empty:
        cov.filters.append(f"{raw_empty:,} rows with empty {time_col} excluded")
    return {"path": src.path, "time": time_col, "grain": grain, "threshold": threshold,
            "first": label(periods[0], grain), "last": label(periods[-1], grain), "periods": len(periods),
            "scored_periods": scored_n, "incomplete": incomplete,
            "seasonality": ({"kind": season["kind"],
                             "factors": {(WEEKDAYS[s] if grain == "day" else f"{s:02d}h"): round(f, 3)
                                         for s, f in sorted(season["factors"].items())}} if season else None),
            "level_shifts": shifts, "findings": findings, "series": series_out,
            "empty_periods": empty, "rows_excluded": unparsed + raw_empty,
            "notes": notes, "coverage": cov}


def split_by_segment(con, by, grain, sp, sc, shifts, findings, notes):
    """Attribute each row-count shift and row-count anomaly to the --by segments that moved."""
    mask_values = bool(_io.PII_NAME_HINTS.search(by))
    nseg = con.execute("SELECT count(DISTINCT _seg) FROM b WHERE _ts IS NOT NULL").fetchone()[0]
    top = [r[0] for r in con.execute(f"SELECT _seg FROM b WHERE _ts IS NOT NULL GROUP BY 1 "
                                     f"ORDER BY count(*) DESC, 1 LIMIT {MAX_SEGMENTS}").fetchall()]
    if nseg > MAX_SEGMENTS:
        notes.append(f"--by {by}: {nseg:,} values; the {MAX_SEGMENTS} largest are kept, the rest are '(other)'")
    if mask_values:
        notes.append(f"--by {by}: the column name looks like personal data, so its values are masked")
    keep = ", ".join(lit(s) for s in top)
    idx = {p: i for i, p in enumerate(sp)}
    per = {}
    for p, s, n in con.execute(
            f"SELECT date_trunc({lit(grain)}, _ts), CASE WHEN _seg IN ({keep}) THEN _seg ELSE '(other)' END, "
            f"count(*) FROM b WHERE _ts IS NOT NULL GROUP BY 1, 2").fetchall():
        if p in idx:
            per.setdefault(s, [0] * len(sp))[idx[p]] = n
    cut = len(sp)
    for sh in shifts:
        if sh["kind"] != "rows":
            continue
        k = cut = sh["index"]
        total = sum(sc[k:]) / (len(sp) - k) - sum(sc[:k]) / k
        parts = []
        for s, v in per.items():
            b, a = sum(v[:k]) / k, sum(v[k:]) / (len(sp) - k)
            parts.append({"segment": shown(s, mask_values), "before_per_period": b, "after_per_period": a,
                          "change_per_period": a - b, "share_of_change": (a - b) / total if total else None})
        sh["by"] = sorted(parts, key=lambda r: -abs(r["change_per_period"]))
    for f in findings:
        if f["kind"] != "rows" or f["expected"] is None:
            continue
        i = f["index"]
        lo, hi = (cut, len(sp)) if i >= cut else (0, cut)
        side_total = sum(sc[lo:hi]) or 1
        dev = f["value"] - f["expected"]
        parts = []
        for s, v in per.items():
            exp = f["expected"] * sum(v[lo:hi]) / side_total
            parts.append({"segment": shown(s, mask_values), "actual": v[i], "expected": exp,
                          "deviation": v[i] - exp, "share_of_deviation": (v[i] - exp) / dev if dev else None})
        f["by"] = sorted(parts, key=lambda r: -abs(r["deviation"]))[:5]


def num(v, kind):
    if v is None:
        return "n/a"
    if kind == "null_rate":
        return f"{100 * v:.1f}%"
    return f"{v:,.0f}" if kind == "rows" else f"{v:,.2f}"


def render(r) -> str:
    L = [f"ANOMALY SCAN  {r['path']}",
         f"time: {r['time']} by {r['grain']} · {r['periods']:,} periods {r['first']} → {r['last']}"
         + (f" · {r['empty_periods']} empty" if r["empty_periods"] else "")]
    s = r["seasonality"]
    L.append("seasonality (row counts): " + (f"{s['kind']} factors "
                                             + "  ".join(f"{k} {v:.2f}" for k, v in s["factors"].items())
                                             if s else "none applied"))
    if r["incomplete"]:
        L.append(f"not scored (incomplete): {', '.join(r['incomplete']['periods'])} — {r['incomplete']['reason']}")
    L += ["", "LEVEL SHIFTS  (strongest one per series; t >= 6 and change >= 5%)"]
    if not r["level_shifts"]:
        L.append("  none")
    for sh in r["level_shifts"]:
        k = sh["kind"]
        adj = " (seasonally adjusted)" if k == "rows" and s else ""
        L.append(f"  {sh['series']:<28} {num(sh['before'], k)} → {num(sh['after'], k)} per period{adj} "
                 f"({100 * sh['change']:+.1f}%) from {sh['from']}   t={sh['t']:.1f}")
        for g in sh.get("by", [])[:5]:
            share = f"{100 * g['share_of_change']:.0f}% of the change" if g["share_of_change"] is not None else ""
            L.append(f"    {g['segment']:<24} {g['before_per_period']:>9,.1f} → {g['after_per_period']:>9,.1f}"
                     f"   {g['change_per_period']:+,.1f}   {share}")
    L += ["", f"POINT ANOMALIES  (|robust z| > {r['threshold']}; empty periods always listed)"]
    if not r["findings"]:
        L.append("  none")
    for f in r["findings"]:
        k = f["kind"]
        z = "z      ∞" if f["z"] is None else f"z {f['z']:+6.1f}"
        L.append(f"  {f['period']:<14} {f['series']:<28} {num(f['value'], k):>10}  "
                 f"expected ~{num(f['expected'], k):<10} {z}  {f['type']}")
        for g in f.get("by", [])[:3]:
            share = f"{100 * g['share_of_deviation']:.0f}%" if g["share_of_deviation"] is not None else ""
            L.append(f"      {g['segment']:<22} {g['actual']:>7,} vs ~{g['expected']:,.0f}  "
                     f"{g['deviation']:+,.0f}  {share}")
    L += ["", "These are OBSERVATIONS. Check a cause before calling it one "
              "(references/root-cause-investigation.md)."]
    if r["notes"]:
        L += ["", "NOTES"] + [f"  - {n}" for n in r["notes"]]
    L += ["", r["coverage"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--time", required=True)
    ap.add_argument("--grain", choices=GRAINS, default="day")
    ap.add_argument("--metric", default="")
    ap.add_argument("--nulls", default="")
    ap.add_argument("--by")
    ap.add_argument("--threshold", type=float, default=3.5)
    ap.add_argument("--seasonal", choices=("auto", "none"), default="auto")
    ap.add_argument("--complete-through", help="YYYY-MM-DD: periods ending after this are not scored")
    ap.add_argument("--fail-on-anomaly", action="store_true", help="exit 1 if anything is flagged (for monitors)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    split = lambda s: [c.strip() for c in s.split(",") if c.strip()]  # noqa: E731
    if a.complete_through:
        try:
            date.fromisoformat(a.complete_through)
        except ValueError:
            print("--complete-through must be YYYY-MM-DD", file=sys.stderr)
            return _io.EXIT_USAGE
    r = scan(a.path, a.time, a.grain, split(a.metric), split(a.nulls), a.by, a.threshold, a.seasonal,
             a.complete_through, a.allow_extension_download)
    if r.get("error"):
        print(r["message"], file=sys.stderr)
        return _io.EXIT_EXTENSION_REQUIRED if r["error"] == "extension_required" else _io.EXIT_USAGE
    for f in r["findings"]:
        f.pop("index")
    if a.json:
        _io.emit_json(r)
    else:
        print(render(r))
    return _io.EXIT_FINDINGS if a.fail_on_anomaly and (r["findings"] or r["level_shifts"]) else 0


if __name__ == "__main__":
    sys.exit(main())
