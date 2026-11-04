#!/usr/bin/env python3
"""Static review of a dbt project: tests, incremental configs, references and model SQL.

    python3 dbt_check.py <project_dir> [--dialect snowflake] [--json] [--fail-on high|warn]

Works without dbt installed and never connects to a warehouse. Jinja is rendered
minimally (ref/source/this become placeholders; {% if is_incremental() %} bodies
are kept), so custom macros may leave a model unparsed — that is reported, not
guessed. For exact SQL, run `dbt compile` and point sql_check.py at target/compiled/.

Exit codes: 0 ok · 1 --fail-on threshold reached · 2 usage · 5 not a dbt project
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402

try:
    import yaml
except ImportError:
    print("This script needs PyYAML (dbt itself depends on it):\n    pip install pyyaml", file=sys.stderr)
    sys.exit(_io.EXIT_USAGE)
import sql_check as SC  # noqa: E402
from sqlglot import exp  # noqa: E402

SEVERITY = {"high": 1, "warn": 2, "perf": 3, "info": 4}
UNIQUE_TESTS = re.compile(r"(^|\.)(unique|unique_combination_of_columns|expect_compound_columns_to_be_unique)$")
REF = re.compile(r"\{\{\s*ref\(\s*(?:['\"][\w.]+['\"]\s*,\s*)?['\"]([\w.]+)['\"]\s*(?:,[^)]*)?\)\s*\}\}")
SOURCE = re.compile(r"\{\{\s*source\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)\s*\}\}")
CONFIG = re.compile(r"\{\{\s*config\((.*?)\)\s*\}\}", re.S)


def finding(rule, sev, msg):
    return {"rule": rule, "severity": sev, "message": msg}


def load_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        return {"__error__": str(e).splitlines()[0]}


TEST_KEYS = {"arguments", "config", "name", "description", "test_name", "column_name"}
MACRO_NS = re.compile(r"\{\{-?\s*(\w+)\.\w+\(")
BUILTIN_NS = {"dbt", "adapter", "config", "this", "model", "modules", "exceptions", "target", "graph",
              "flags", "builtins", "api", "invocation_args_dict", "selected_resources", "context"}


def installed_packages(root):
    """Package namespaces from packages.yml / dependencies.yml; None if one cannot be named (git/local)."""
    names = set()
    for f in ("packages.yml", "dependencies.yml"):
        y = load_yaml(os.path.join(root, f)) if os.path.exists(os.path.join(root, f)) else {}
        for p in (y.get("packages") or []) if isinstance(y, dict) else []:
            if not isinstance(p, dict) or "package" not in p:
                return None  # git or local package: its namespace is not in the file
            names.add(str(p["package"]).split("/")[-1])
    return names


def top_level_test_args(tests):
    """Generic tests whose arguments sit beside the test name, not under `arguments:`.

    dbt 1.10+ deprecates that form (MissingArgumentsPropertyInGenericTestDeprecation);
    confirmed against dbt-core 1.12 `dbt parse`.
    """
    out = []
    for t in tests or []:
        if isinstance(t, dict):
            for name, args in t.items():
                if isinstance(args, dict) and set(args) - TEST_KEYS:
                    out.append(name)
    return out


def test_names(tests):
    out = []
    for t in tests or []:
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            out.extend(t.keys())
    return out


def sql_config(sql):
    """Literal keyword arguments of {{ config(...) }}; non-literal values are skipped."""
    m = CONFIG.search(sql)
    if not m:
        return {}
    try:
        call = ast.parse(f"f({m.group(1)})", mode="eval").body
    except SyntaxError:
        return {}
    cfg = {}
    for k in call.keywords:
        try:
            cfg[k.arg] = ast.literal_eval(k.value)
        except ValueError:
            cfg[k.arg] = "<non-literal>"
    return cfg


def render(sql):
    """Minimal Jinja rendering: enough for sqlglot to read the model's shape."""
    s = re.sub(r"\{#.*?#\}", "", sql, flags=re.S)
    s = CONFIG.sub("", s)
    s = REF.sub(lambda m: f"__ref__{m.group(1).replace('.', '_')}", s)
    s = SOURCE.sub(lambda m: f"__src__{m.group(1)}__{m.group(2)}", s)
    s = re.sub(r"\{\{\s*this\s*\}\}", "__this__", s)
    s = re.sub(r"\{%-?.*?-?%\}", "", s, flags=re.S)
    s = re.sub(r"\{\{.*?\}\}", "'__jinja__'", s, flags=re.S)
    return s


def import_cte_star(sel) -> bool:
    """`with x as (select * from {{ ref(...) }})`: dbt's recommended import CTE, not a SELECT * smell."""
    frm = sel.args.get("from_") or sel.args.get("from")  # key renamed to from_ in sqlglot 30
    return (isinstance(sel.parent, exp.CTE) and not sel.args.get("joins") and not sel.args.get("where")
            and isinstance(frm, exp.From) and isinstance(frm.this, exp.Table) and frm.this.name.startswith("__"))


def project_configs(tree, path=()):
    """Flatten dbt_project.yml `models:` into {path tuple: {config}} for '+key' entries."""
    out = {}
    if not isinstance(tree, dict):
        return out
    here = {k[1:]: v for k, v in tree.items() if k.startswith("+")}
    if here:
        out[path] = here
    for k, v in tree.items():
        if not k.startswith("+") and isinstance(v, dict):
            out.update(project_configs(v, path + (k,)))
    return out


def check_project(root, dialect=None) -> dict:
    proj_file = os.path.join(root, "dbt_project.yml")
    if not os.path.exists(proj_file):
        return {"error": f"no dbt_project.yml in {root}"}
    proj = load_yaml(proj_file)
    if "__error__" in proj:
        return {"error": f"dbt_project.yml does not parse: {proj['__error__']}"}
    name = proj.get("name", "")
    model_paths = proj.get("model-paths") or proj.get("source-paths") or ["models"]
    pconf = project_configs((proj.get("models") or {}).get(name, {}))

    models, yml_models, sources, problems = {}, {}, {}, []
    for mp in model_paths:
        base = os.path.join(root, mp)
        for dirpath, _, files in os.walk(base):
            for f in sorted(files):
                full = os.path.join(dirpath, f)
                rel_dir = tuple(p for p in os.path.relpath(dirpath, base).split(os.sep) if p != ".")
                if f.endswith(".sql"):
                    models[f[:-4]] = {"path": os.path.relpath(full, root), "dir": rel_dir,
                                      "sql": open(full, encoding="utf-8").read()}
                elif f.endswith((".yml", ".yaml")):
                    y = load_yaml(full)
                    if "__error__" in y:
                        problems.append(f"{os.path.relpath(full, root)}: YAML error: {y['__error__']}")
                        continue
                    for m in y.get("models") or []:
                        if isinstance(m, dict) and m.get("name"):
                            yml_models[m["name"]] = m
                    for s in y.get("sources") or []:
                        for t in s.get("tables") or []:
                            sources[(s["name"], t["name"])] = {
                                "freshness": t.get("freshness", s.get("freshness")),
                                "loaded_at_field": t.get("loaded_at_field", s.get("loaded_at_field")),
                                "event_time": ((t.get("config") or {}).get("event_time")
                                               or (s.get("config") or {}).get("event_time"))}

    def model_cfg(mname):
        m, cfg = models[mname], {}
        for i in range(len(m["dir"]) + 1):
            cfg.update(pconf.get(m["dir"][:i], {}))
        cfg.update((yml_models.get(mname, {}).get("config") or {}))
        cfg.update(sql_config(m["sql"]))
        return cfg

    results = []
    for mname, m in sorted(models.items()):
        cfg = model_cfg(mname)
        y = yml_models.get(mname, {})
        out = []

        # tests / documentation
        if not y:
            out.append(finding("DB01", "info", "no YAML entry: undocumented and untested"))
        tests = test_names(y.get("data_tests") or y.get("tests"))
        for c in y.get("columns") or []:
            tests += test_names(c.get("data_tests") or c.get("tests"))
        old_style = top_level_test_args(y.get("data_tests") or y.get("tests"))
        for c in y.get("columns") or []:
            old_style += top_level_test_args(c.get("data_tests") or c.get("tests"))
        for t in sorted(set(old_style)):
            out.append(finding("DB12", "info", f"test '{t}' has its arguments at the top level: dbt 1.10+ "
                               "deprecates this; nest them under 'arguments:'"))
        if not any(UNIQUE_TESTS.search(t) for t in tests):
            out.append(finding("DB02", "warn", "no uniqueness test: the model's grain is never checked "
                               "(add unique + not_null on the key, or unique_combination_of_columns)"))

        # references
        for ref in REF.findall(m["sql"]):
            if ref not in models:
                out.append(finding("DB08", "warn", f"ref('{ref}') is not a model in this project (a package model, "
                                   "or a typo?)"))
        for src in SOURCE.findall(m["sql"]):
            if src not in sources:
                out.append(finding("DB08", "warn", f"source('{src[0]}', '{src[1]}') is not declared in any YAML"))

        # incremental
        inc = cfg.get("materialized") == "incremental"
        has_inc_block = "is_incremental()" in re.sub(r"--[^\n]*|\{#.*?#\}|/\*.*?\*/", "", m["sql"], flags=re.S)
        if inc:
            if not has_inc_block and cfg.get("incremental_strategy") != "microbatch":  # microbatch filters by event_time itself
                out.append(finding("DB04", "high", "incremental model without {% if is_incremental() %}: every run "
                                   "re-reads everything (and with append, duplicates it)"))
            strategy = cfg.get("incremental_strategy")
            if strategy == "microbatch":
                missing = [k for k in ("event_time", "begin", "batch_size") if not cfg.get(k)]
                if missing:
                    out.append(finding("DB13", "high", f"microbatch model without {', '.join(missing)}: "
                                       "dbt refuses to parse it"))
                blind = [f"ref('{r}')" for r in REF.findall(m["sql"]) if r in models and not model_cfg(r).get("event_time")]
                blind += [f"source('{a}', '{b}')" for a, b in SOURCE.findall(m["sql"])
                          if (a, b) in sources and not sources[(a, b)]["event_time"]]
                if blind:
                    out.append(finding("DB14", "warn", f"microbatch input {', '.join(blind)} has no event_time: "
                                       "dbt cannot filter it per batch, so every batch reads all of it "
                                       "(duplicates or slow runs)"))
            if not cfg.get("unique_key") and strategy not in ("insert_overwrite", "microbatch"):
                out.append(finding("DB05", "warn", "incremental without unique_key: re-running a period appends its "
                                   "rows again"))
            if not cfg.get("on_schema_change"):
                out.append(finding("DB06", "info", "on_schema_change not set: the default 'ignore' silently leaves "
                                   "new source columns out of the table"))

        # SQL shape
        rendered = render(m["sql"])
        try:
            stmts = [s for s in SC.sqlglot.parse(rendered, read=dialect)
                     if s is not None and not isinstance(s, exp.Semicolon)]
        except Exception as e:  # macros we cannot render, dialect mismatch
            stmts = []
            out.append(finding("DB00", "info", f"model SQL not analysed after minimal Jinja rendering "
                               f"({type(e).__name__}); run dbt compile and sql_check.py on target/compiled/"))
        ctes = set()
        for st in stmts:
            ctes |= {c.alias_or_name for c in st.find_all(exp.CTE)}
            for t in st.find_all(exp.Table):
                n = t.name
                if n and not n.startswith("__") and n not in ctes and not isinstance(t.this, exp.Func):
                    out.append(finding("DB03", "warn", f"hard-coded relation {SC.table_name(t)}: use ref() or source() "
                                       "so lineage, environments and freshness work"))
            if inc:
                for g in st.find_all(exp.GT):
                    if any(t.name == "__this__" for t in g.find_all(exp.Table)):
                        out.append(finding("DB07", "warn", "incremental filter uses > against the target's max: rows "
                                           "sharing that timestamp are skipped. Use >= with a lookback (unique_key dedupes)"))
            stars_outside_imports = any(
                any(isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
                    for e in sel.expressions) and not import_cte_star(sel)
                for sel in st.find_all(exp.Select))
            for f in SC.rules(st):
                if f["rule"] == "SQ12" or (f["rule"] == "SQ01" and not stars_outside_imports):
                    continue
                out.append(finding(f["rule"], f["severity"], f["message"]))
        out = list({(f["rule"], f["message"]): f for f in out}.values())  # one line per distinct finding
        out.sort(key=lambda f: (SEVERITY[f["severity"]], f["rule"]))
        results.append({"model": mname, "path": m["path"], "materialized": cfg.get("materialized", "view (default)"),
                        "findings": out})

    extra = []
    have = installed_packages(root)
    if have is not None:
        used = {}
        for mname, m in models.items():
            for ns in MACRO_NS.findall(m["sql"]):
                used.setdefault(ns, set()).add(mname)
        for mname, y in yml_models.items():
            tests = test_names(y.get("data_tests") or y.get("tests"))
            for c in y.get("columns") or []:
                tests += test_names(c.get("data_tests") or c.get("tests"))
            for t in tests:
                if "." in t:
                    used.setdefault(t.split(".")[0], set()).add(mname)
        for ns, where in sorted(used.items()):
            if ns not in have and ns not in BUILTIN_NS and ns != name:
                extra.append(finding("DB15", "high", f"'{ns}' is used ({', '.join(sorted(where))}) but no packages.yml "
                                     f"or dependencies.yml installs it: dbt parse passes, compile and build fail "
                                     f"with \"'{ns}' is undefined\""))
    for yname in sorted(set(yml_models) - set(models)):
        extra.append(finding("DB11", "info", f"YAML documents '{yname}', which has no .sql model"))
    for (s, t), v in sorted(sources.items()):
        if not v["freshness"]:
            extra.append(finding("DB09", "info", f"source {s}.{t} has no freshness check: a stale load is not noticed"))
    return {"project": name, "models": results, "project_findings": extra, "problems": problems}


def render_report(r) -> str:
    L, counts = [f"DBT CHECK  ·  project '{r['project']}'  ·  {len(r['models'])} models"], {}
    for m in r["models"]:
        L.append(f"\n{m['model']}  ({m['materialized']})  {m['path']}")
        for f in m["findings"]:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
            L.append(f"  {f['severity'].upper():<5} {f['rule']}  {f['message']}")
        if not m["findings"]:
            L.append("  no findings")
    if r["project_findings"]:
        L.append("\nPROJECT")
        for f in r["project_findings"]:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
            L.append(f"  {f['severity'].upper():<5} {f['rule']}  {f['message']}")
    if r["problems"]:
        L += ["\nPROBLEMS"] + [f"  - {p}" for p in r["problems"]]
    L.append("\nSUMMARY  " + (", ".join(f"{counts[k]} {k}" for k in SEVERITY if k in counts) or "no findings")
             + "  ·  static review: nothing compiled or run (NOT_VERIFIED in dbt)")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    ap.add_argument("--dialect", help="the warehouse: snowflake, bigquery, postgres, databricks, duckdb, …")
    ap.add_argument("--fail-on", choices=["high", "warn"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = check_project(a.project_dir, a.dialect)
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        return _io.EXIT_READ_ERROR
    if a.json:
        _io.emit_json(r)
    else:
        print(render_report(r))
    sev = [SEVERITY[f["severity"]] for m in r["models"] for f in m["findings"]] + \
          [SEVERITY[f["severity"]] for f in r["project_findings"]]
    if a.fail_on and sev and min(sev) <= SEVERITY[a.fail_on]:
        return _io.EXIT_FINDINGS
    return 0


if __name__ == "__main__":
    sys.exit(main())
