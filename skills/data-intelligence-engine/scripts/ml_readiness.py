#!/usr/bin/env python3
"""Check whether a dataset is ready to train a model on: target, leakage, splits.

    python3 ml_readiness.py <path> --target COL [--positive VALUE]
            [--prediction-time COL] [--feature-time FEATURE=TIMECOL ...]
            [--time COL] [--split COL] [--group COL] [--json]

It does the data side only. It never trains, tunes or evaluates a model.

TARGET    type (binary / multiclass / regression / constant), unlabelled rows,
          class balance, minority events per feature
LEAKAGE   per feature, how well it ALONE separates the target:
            numbers and dates vs a binary target: AUC (rank based)
            categories vs a binary target (missing counted as a value): AUC
            of the category's own positive rate (in-sample, so up to 50 or
            5% of rows distinct values only)
            categories vs a multiclass target: purity gain over the
            majority-class baseline
            numbers vs a numeric target: |Spearman|
          >= 0.98 is a suspected leak (BLOCKER); 0.90-0.98 must be checked
          missingness that differs by class (it can encode the outcome)
          names that suggest something recorded after the outcome
          with --prediction-time: date features later than the prediction
          moment, and --feature-time FEATURE=TIMECOL pairs whose timestamp is
          later ("was this feature available at prediction time?")
FEATURES  identifiers (memorisation), constants, personal data, free text
ROWS      exact duplicates; identical features with different labels
SPLITS    --time: label rate by month; --split: rows per split, evaluation
          rows older than the newest training row, --group values present in
          both training and evaluation

VERDICT   NOT READY (any blocker) · READY AFTER CHECKS (checks open) ·
          READY WITH CAVEATS (warnings only) · READY
No feature values are printed; only column names and aggregates.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402
import profile_dataset as P  # noqa: E402
from _common import lit, q  # noqa: E402

LEAK, CHECK = 0.98, 0.90
MISSING_GAP = 0.20         # missing share differing by this much between classes is a check
MINORITY_SHARE = 0.10
EVENTS_PER_FEATURE = 10
MIN_CLASS_ROWS = 30
CATEGORY_MAX = 50
POST_OUTCOME_NAME = re.compile(
    r"(^|_)(refund\w*|cancel\w*|churn\w*|outcome|result|label|target|resolution|resolved|closed|"
    r"terminat\w*|chargeback|after|post|final|response|returned|default(ed)?|fraud\w*)($|_)", re.I)


def missing_sql(x: str) -> str:
    s = f"lower(trim(CAST({x} AS VARCHAR)))"
    return f"({x} IS NULL OR {s} = '' OR {s} IN ({', '.join(lit(p) for p in _io.PLACEHOLDERS)}))"


def family(c):
    if c["kind"] == "numeric" or c.get("inferred_type") in ("numeric (text)", "money (text)", "mixed: mostly numeric"):
        return "number"
    if c["kind"] == "temporal" or c.get("inferred_type") in ("date (text)", "mixed: mostly dates"):
        return "date"
    return "text"


def value_sql(c):
    x = q(c["name"])
    if family(c) == "number":
        return f"CAST({x} AS DOUBLE)" if c["kind"] == "numeric" else P.num_expr(f"CAST({x} AS VARCHAR)")
    if family(c) == "date":
        return f"CAST({P.date_value_expr(c) or f'TRY_CAST({x} AS DATE)'} AS DATE)"
    return f"trim(CAST({x} AS VARCHAR))"


def auc(con, v, pos, source="lab"):
    """Rank AUC of v for the positive class (ties get average ranks); None if a class is empty."""
    s, n1, n0 = con.execute(
        f"WITH d AS (SELECT {v} v, _y = {lit(pos)} p FROM {source} WHERE {v} IS NOT NULL), "
        f"r AS (SELECT p, rank() OVER (ORDER BY v) + (count(*) OVER (PARTITION BY v) - 1) / 2.0 rk FROM d) "
        f"SELECT sum(rk) FILTER (WHERE p), count(*) FILTER (WHERE p), count(*) FILTER (WHERE NOT p) FROM r"
    ).fetchone()
    if not n1 or not n0:
        return None
    return (float(s) - n1 * (n1 + 1) / 2) / (n1 * n0)


def check(path, target, positive=None, prediction_time=None, feature_times=None, time_col=None,
          split=None, group=None, allow_download=False) -> dict:
    prof = P.profile(path, allow_download=allow_download)
    if prof.get("error"):
        return prof
    cols = {c["name"]: c for c in prof["columns"]}
    feature_times = feature_times or {}
    named = [target, prediction_time, time_col, split, group, *feature_times, *feature_times.values()]
    unknown = [n for n in named if n and n not in cols]
    if unknown:
        return {"error": "unknown_column", "message": "column(s) not in the data: " + ", ".join(unknown)}
    con = _io.connect()
    src = _io.open_source(path)
    _io.create_view(con, src, allow_download)
    rows = prof["rows"]
    blockers, checks, warnings, notes = [], [], [], []
    tc = cols[target]

    # ---------------- target ----------------
    tfam = family(tc)
    con.execute(f"CREATE TEMP TABLE lab AS SELECT *, trim(CAST({q(target)} AS VARCHAR)) AS _y, "
                f"{value_sql(tc) if tfam == 'number' else 'NULL::DOUBLE'} AS _yn FROM src "
                f"WHERE NOT {missing_sql(q(target))}")
    labelled = con.execute("SELECT count(*) FROM lab").fetchone()[0]
    unlabelled = rows - labelled
    classes = con.execute("SELECT _y, count(*) FROM lab GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()
    if len(classes) <= 1:
        kind = "constant"
    elif len(classes) == 2:
        kind = "binary"
    elif tfam == "number" and len(classes) > 20:
        kind = "regression"
    else:
        kind = "multiclass"
    if unlabelled:
        warnings.append({"what": "unlabelled rows", "column": target,
                         "detail": f"{unlabelled:,} of {rows:,} rows have no {target}; they are excluded below"})
    if kind == "constant":
        blockers.append({"what": "target has one value" if labelled else "no labelled rows", "column": target,
                         "detail": "nothing to learn: every labelled row has the same target" if labelled
                         else f"every row's {target} is empty"})
    target_info = {"column": target, "kind": kind, "labelled": labelled, "unlabelled": unlabelled}
    pos = None
    if kind == "binary":
        pos = positive if positive is not None else classes[-1][0]
        if pos not in dict(classes):
            return {"error": "bad_positive", "message": f"--positive {pos!r} is not a value of {target}"}
        npos = dict(classes)[pos]
        target_info.update({"positive": pos, "positives": npos, "positive_share": npos / labelled})
    if kind in ("binary", "multiclass"):
        target_info["classes"] = [{"value": v if n >= P.SMALL_COUNT else "(rare)", "rows": n, "share": n / labelled}
                                  for v, n in classes]
        minority = classes[-1][1]
        if minority / labelled < MINORITY_SHARE:
            warnings.append({"what": "class imbalance", "column": target,
                             "detail": f"smallest class is {100 * minority / labelled:.1f}% ({minority:,} rows): "
                                       "accuracy will mislead; use PR-AUC or recall and stratify the split"})
        small = [v for v, n in classes if n < MIN_CLASS_ROWS]
        if small:
            warnings.append({"what": "tiny classes", "column": target,
                             "detail": f"{len(small)} class(es) under {MIN_CLASS_ROWS} rows: too few to learn or evaluate"})
    if kind == "regression":
        target_info.update(dict(zip(("min", "median", "max"),
                                    con.execute("SELECT min(_yn), median(_yn), max(_yn) FROM lab").fetchone())))

    # ---------------- features ----------------
    reserved = {target, prediction_time, time_col, split, *feature_times.values()} - {None}
    feats = [n for n in cols if n not in reserved]
    out = {}
    for name in feats:
        c = cols[name]
        rec = out[name] = {"column": name, "family": family(c), "role": None}
        ident = c.get("key_candidate") or c.get("inferred_type") == "identifier-like text" or \
            (_io.KEY_NAME_HINTS.search(name) and c["distinct"] >= 0.9 * max(c["present"], 1))
        if name == group or ident:
            rec["role"] = "identifier"
            warnings.append({"what": "identifier as feature", "column": name,
                             "detail": "lets a model memorise rows: drop it, or use it only to group the split"})
            continue
        # one value and no gaps (or all gaps) is constant; one value plus gaps is a flag whose presence may leak
        if c["present"] == 0 or (c["distinct"] <= 1 and c["present"] == rows):
            rec["role"] = "constant"
            warnings.append({"what": "constant feature", "column": name, "detail": "one value: carries no signal"})
            continue
        if c.get("pii"):
            notes.append(f"{name}: personal data ({c['pii']}); justify using it (references/privacy-and-pii.md)")
        if c.get("inferred_type") == "free text":
            rec["role"] = "free text"
            notes.append(f"{name}: free text, not scored for leakage; read its meaning before using it")
            continue
        x = q(name)
        if POST_OUTCOME_NAME.search(name):
            checks.append({"what": "name suggests post-outcome data", "column": name,
                           "detail": "confirm it is known before the prediction moment"})
        if kind == "binary":
            mp, mn = con.execute(
                f"SELECT avg(CASE WHEN {missing_sql(x)} THEN 1 ELSE 0 END) FILTER (WHERE _y = {lit(pos)}), "
                f"avg(CASE WHEN {missing_sql(x)} THEN 1 ELSE 0 END) FILTER (WHERE _y <> {lit(pos)}) FROM lab"
            ).fetchone()
            rec["missing_positive"], rec["missing_negative"] = mp, mn
            gap = abs(mp - mn)
            # a missing-or-not flag used as a predictor has AUC 0.5 x (1 + gap)
            if 0.5 * (1 + gap) >= LEAK:
                blockers.append({"what": "missingness alone predicts the target", "column": name,
                                 "detail": f"missing in {100 * mp:.1f}% of {pos} rows vs {100 * mn:.1f}% of others"})
            elif gap >= MISSING_GAP:
                checks.append({"what": "missingness differs by class", "column": name,
                               "detail": f"missing in {100 * mp:.1f}% of {pos} rows vs {100 * mn:.1f}% of others: "
                                         "it may be filled only after the outcome"})
        sep, metric, fam = None, None, family(c)
        if fam in ("number", "date") and kind == "binary":
            v = value_sql(c) if fam == "number" else f"date_diff('day', DATE '1970-01-01', {value_sql(c)})"
            a = auc(con, v, pos)
            if a is not None:
                sep, metric = max(a, 1 - a), "AUC"
        elif fam == "number" and kind == "regression":
            v = value_sql(c)
            r = con.execute(f"SELECT corr(rx, ry) FROM (SELECT rank() OVER (ORDER BY {v}) rx, "
                            f"rank() OVER (ORDER BY _yn) ry FROM lab WHERE {v} IS NOT NULL AND _yn IS NOT NULL)"
                            ).fetchone()[0]
            if r is not None:
                sep, metric = abs(r), "|Spearman|"
        elif kind == "binary" and c["distinct"] <= max(CATEGORY_MAX, 0.05 * rows):
            # each category scored by its own positive rate: the best ranking the category alone allows
            f_ = f"CASE WHEN {missing_sql(x)} THEN '(missing)' ELSE trim(CAST({x} AS VARCHAR)) END"
            enc = (f"(SELECT _y, avg(CASE WHEN _y = {lit(pos)} THEN 1.0 ELSE 0 END) OVER (PARTITION BY {f_}) "
                   f"AS enc FROM lab)")
            a = auc(con, "enc", pos, enc)
            if a is not None:
                sep, metric = max(a, 1 - a), "AUC"
        elif kind == "multiclass" and c["distinct"] <= max(CATEGORY_MAX, 0.05 * rows):
            v = f"CASE WHEN {missing_sql(x)} THEN '(missing)' ELSE trim(CAST({x} AS VARCHAR)) END"
            pure = con.execute(f"SELECT sum(m) FROM (SELECT max(n) m FROM (SELECT {v} f, _y, count(*) n FROM lab "
                               f"GROUP BY 1, 2) GROUP BY f)").fetchone()[0] / labelled
            base = classes[0][1] / labelled
            sep, metric = (pure - base) / (1 - base), "purity gain"
        rec["separation"], rec["metric"] = sep, metric
        if sep is not None and sep >= LEAK:
            blockers.append({"what": "suspected leak: separates the target almost perfectly", "column": name,
                             "detail": f"{metric} {sep:.3f} on its own: real predictors rarely do this"})
        elif sep is not None and sep >= CHECK:
            checks.append({"what": "very strong single predictor", "column": name,
                           "detail": f"{metric} {sep:.3f}: confirm it is available at prediction time"})

    # ---------------- availability at prediction time ----------------
    if prediction_time:
        pt = value_sql(cols[prediction_time])
        pairs = [(n, n) for n in feats if out[n]["role"] is None and family(cols[n]) == "date"]
        pairs += list(feature_times.items())
        for feat, tcol in pairs:
            tv = value_sql(cols[tcol])
            later, known = con.execute(
                f"SELECT count(*) FILTER (WHERE {tv} > {pt}), count(*) FILTER (WHERE {tv} IS NOT NULL "
                f"AND {pt} IS NOT NULL) FROM lab WHERE NOT {missing_sql(q(feat))}").fetchone()
            if later:
                via = "" if feat == tcol else f" (by {tcol})"
                checks.append({"what": "dated after the prediction moment", "column": feat,
                               "detail": f"{later:,} of {known:,} rows{via} are later than {prediction_time}: "
                                         "not known when the prediction is made, unless it is a scheduled date"})
    else:
        notes.append("no --prediction-time: availability at prediction time was NOT checked")

    # ---------------- rows ----------------
    fcols = [n for n in feats if out[n]["role"] != "identifier"]
    rows_info = {}
    if fcols:
        dup, conflict = con.execute(
            f"SELECT coalesce(sum(n - 1), 0), coalesce(sum(n) FILTER (WHERE k > 1), 0) FROM "
            f"(SELECT count(*) n, count(DISTINCT _y) k FROM lab GROUP BY {', '.join(q(n) for n in fcols)} "
            f"HAVING count(*) > 1)").fetchone()
        rows_info = {"duplicate_feature_rows": int(dup), "conflicting_label_rows": int(conflict)}
        if conflict:
            warnings.append({"what": "same features, different labels", "column": "*",
                             "detail": f"{int(conflict):,} rows share identical features but not the label: "
                                       "label noise, or a missing feature"})
        if dup:
            warnings.append({"what": "duplicate feature rows", "column": "*",
                             "detail": f"{int(dup):,} extra copies: keep copies on one side of the split"})
    usable = sum(1 for r in out.values() if r["role"] is None)
    if kind == "binary":
        smaller = min(target_info["positives"], labelled - target_info["positives"])
        if usable and smaller < EVENTS_PER_FEATURE * usable:
            warnings.append({"what": "few events per feature", "column": target,
                             "detail": f"smaller class has {smaller:,} rows for {usable} features "
                                       f"(< {EVENTS_PER_FEATURE} per feature): overfitting risk"})

    # ---------------- time and splits ----------------
    splits = {}
    yrate = (f"avg(CASE WHEN _y = {lit(pos)} THEN 1.0 ELSE 0 END)" if kind == "binary"
             else "avg(_yn)" if kind == "regression" else "NULL")
    if time_col:
        tv = value_sql(cols[time_col])
        splits["label_by_month"] = [
            {"month": m, "rows": n, "label": r} for m, n, r in con.execute(
                f"SELECT strftime(date_trunc('month', {tv}), '%Y-%m') m, count(*), {yrate} FROM lab "
                f"WHERE {tv} IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()]
        if not split:
            checks.append({"what": "time-dependent data", "column": time_col,
                           "detail": "split by time (train on earlier, evaluate on later), not at random"})
    if split:
        sv = f"trim(CAST({q(split)} AS VARCHAR))"
        parts = con.execute(f"SELECT {sv}, count(*), {yrate} FROM lab GROUP BY 1 ORDER BY 2 DESC, 1").fetchall()
        train = next((p[0] for p in parts if p[0] and p[0].lower() == "train"), parts[0][0])
        splits["parts"] = [{"split": n, "rows": c, "label": r, "train": n == train} for n, c, r in parts]
        if time_col:
            tv = value_sql(cols[time_col])
            older = con.execute(f"SELECT count(*) FROM lab WHERE {sv} <> {lit(train)} AND {tv} < "
                                f"(SELECT max({tv}) FROM lab WHERE {sv} = {lit(train)})").fetchone()[0]
            splits["evaluation_rows_older_than_train"] = older
            if older:
                checks.append({"what": "evaluation overlaps training in time", "column": split,
                               "detail": f"{older:,} evaluation rows are older than the newest training row: "
                                         "a random split on time-dependent data overstates accuracy"})
        if group:
            g = f"trim(CAST({q(group)} AS VARCHAR))"
            shared, srows = con.execute(
                f"WITH a AS (SELECT {g} k, bool_or({sv} = {lit(train)}) t, bool_or({sv} <> {lit(train)}) e, "
                f"count(*) FILTER (WHERE {sv} <> {lit(train)}) n FROM lab WHERE {g} IS NOT NULL GROUP BY 1) "
                f"SELECT count(*) FILTER (WHERE t AND e), coalesce(sum(n) FILTER (WHERE t AND e), 0) FROM a"
            ).fetchone()
            splits["shared_groups"], splits["shared_group_eval_rows"] = shared, int(srows)
            if shared:
                blockers.append({"what": "groups leak across the split", "column": group,
                                 "detail": f"{shared:,} {group} values appear in training and evaluation "
                                           f"({int(srows):,} evaluation rows): split by {group}"})

    verdict = ("NOT READY" if blockers else "READY AFTER CHECKS" if checks
               else "READY WITH CAVEATS" if warnings else "READY")
    cov = _io.coverage_for(src, rows, rows)
    if unlabelled:
        cov.filters.append(f"{unlabelled:,} rows without {target} excluded")
    return {"path": src.path, "rows": rows, "target": target_info, "features": list(out.values()),
            "rows_check": rows_info, "splits": splits, "blockers": blockers, "checks": checks,
            "warnings": warnings, "notes": notes, "verdict": verdict, "coverage": cov,
            "boundary": "data side only: no model was trained, tuned or evaluated (decision D1)"}


def render(r) -> str:
    t = r["target"]
    L = [f"ML READINESS  {r['path']}", f"target: {t['column']} ({t['kind']}) · {t['labelled']:,} labelled rows"
         + (f" · {t['unlabelled']:,} unlabelled" if t["unlabelled"] else "")]
    if t.get("classes"):
        L.append("  classes: " + " · ".join(f"{c['value']} {c['rows']:,} ({100 * c['share']:.1f}%)"
                                            for c in t["classes"][:8]))
    if t["kind"] == "regression":
        L.append(f"  min {t['min']:,.2f} · median {t['median']:,.2f} · max {t['max']:,.2f}")
    for title, key in (("BLOCKERS", "blockers"), ("CHECKS (confirm with the data owner)", "checks"),
                       ("WARNINGS", "warnings")):
        L += ["", title] + ([f"  - {i['column']}: {i['what']} — {i['detail']}" for i in r[key]] or ["  none"])
    scored = [f for f in r["features"] if f.get("separation") is not None]
    if scored:
        L += ["", "SINGLE-FEATURE SEPARATION  (1.0 = predicts the target alone; ≥ 0.98 suspected leak)"]
        for f in sorted(scored, key=lambda f: -f["separation"])[:12]:
            L.append(f"  {f['column']:<24} {f['metric']:<12} {f['separation']:.3f}")
    s = r["splits"]
    if s.get("parts"):
        L += ["", "SPLIT"] + [f"  {p['split']:<12} {p['rows']:>8,} rows"
                              + (f"   label {p['label']:.3f}" if p["label"] is not None else "")
                              + ("   (training)" if p["train"] else "") for p in s["parts"]]
    m = [x for x in s.get("label_by_month", []) if x["label"] is not None]
    if m:
        lo, hi = min(m, key=lambda x: x["label"]), max(m, key=lambda x: x["label"])
        L += ["", f"label by month: {len(m)} months, lowest {lo['month']} {lo['label']:.3f}, "
                  f"highest {hi['month']} {hi['label']:.3f}"]
    if r["notes"]:
        L += ["", "NOTES"] + [f"  - {n}" for n in r["notes"]]
    L += ["", f"VERDICT (data side): {r['verdict']}", r["boundary"], "", r["coverage"].line()]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--target", required=True)
    ap.add_argument("--positive")
    ap.add_argument("--prediction-time")
    ap.add_argument("--feature-time", action="append", default=[], metavar="FEATURE=TIMECOL")
    ap.add_argument("--time")
    ap.add_argument("--split")
    ap.add_argument("--group")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-extension-download", action="store_true")
    a = ap.parse_args(argv)
    ft = {}
    for pair in a.feature_time:
        if "=" not in pair:
            print(f"--feature-time needs FEATURE=TIMECOL, got {pair!r}", file=sys.stderr)
            return _io.EXIT_USAGE
        f, t = pair.split("=", 1)
        ft[f.strip()] = t.strip()
    r = check(a.path, a.target, a.positive, a.prediction_time, ft, a.time, a.split, a.group,
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
