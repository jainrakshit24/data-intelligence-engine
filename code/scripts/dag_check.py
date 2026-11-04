#!/usr/bin/env python3
"""Static review of Airflow DAG files. The file is parsed, never imported or run.

    python3 dag_check.py <dag.py | dags_dir> [--json] [--fail-on high|warn]

Importing a DAG file executes its top-level code (queries, API calls), so this
reads the source with Python's ast module only. Works without Airflow installed.

Exit codes: 0 ok · 1 --fail-on threshold reached · 2 usage · 5 unreadable · 6 syntax error
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as _io  # noqa: E402

SEVERITY = {"high": 1, "warn": 2, "info": 4}
# Airflow 2 paths that Airflow 3.3 warns about (each import checked against apache-airflow 3.3.2)
AIRFLOW2_PATH = re.compile(r"airflow\.decorators$|airflow\.models\.baseoperator$|"
                           r"airflow\.(operators|sensors)\.(python|bash|empty|filesystem|time_delta)$")
SECRET_NAME = re.compile(r"(password|passwd|pwd|secret|token|api_?key|access_?key|private_?key|credential)", re.I)
# calls that do I/O (network, database, filesystem scans, metadata DB) when made at import time.
# Cheap calls such as os.environ.get, os.path.join or Path(...) are deliberately not listed.
HEAVY = re.compile(r"^(Variable\.get|BaseHook\.get_connection|\w+Hook\.get_connection|"
                   r"(requests|httpx|urllib\.request|urllib3|boto3|subprocess)\.\w+|urlopen|"
                   r"(pd|pandas)\.read_\w+|(psycopg2|pymysql|sqlite3|snowflake\.connector|duckdb)\.connect|"
                   r"(sqlalchemy\.)?create_engine|os\.(listdir|scandir|walk)|glob\.(glob|iglob)|open)$")
# a name that holds the NAME of a secret (conn id, variable key), not the secret itself
SECRET_REF_NAME = re.compile(r"(_name|_id|_var|_conn|_conn_id|_path|_file|_env|_key_name|_variable)$", re.I)


def secret_like(value: str) -> bool:
    """A string that could be a credential: long enough, and not a plain lower_snake name like 'orders_token'."""
    return len(value) >= 6 and not re.fullmatch(r"[a-z_]+", value)
NOW_CALLS = {"datetime.now", "datetime.utcnow", "datetime.today", "date.today", "pendulum.now", "pendulum.today",
             "timezone.utcnow", "time.time", "days_ago", "dates.days_ago", "datetime.datetime.now"}
SENSOR = re.compile(r"Sensor$")


def dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return dotted(node.func)
    return ""


def kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def finding(rule, sev, msg, node, path):
    return {"rule": rule, "severity": sev, "message": msg, "file": path, "line": getattr(node, "lineno", 0)}


def dict_keys(node):
    """Keys of a dict literal or dict(...) call; None if not statically known."""
    if isinstance(node, ast.Dict):
        return {k.value for k in node.keys if isinstance(k, ast.Constant)}
    if isinstance(node, ast.Call) and dotted(node.func) == "dict":
        return {k.arg for k in node.keywords if k.arg}
    return None


def is_dag_call(call):
    return isinstance(call, ast.Call) and dotted(call.func).split(".")[-1] in ("DAG", "dag")


def check_file(path) -> dict:
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as e:
        return {"file": path, "error": f"unreadable: {e}"}
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        return {"file": path, "error": f"syntax error line {e.lineno}: {e.msg}"}
    out, dags = [], []
    names = {}  # module-level name -> value node (for default_args = {...})
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            names[n.targets[0].id] = n.value

    # ---- DAG definitions: DAG(...), with DAG(...), @dag(...) ----
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and is_dag_call(node):
            dags.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                if is_dag_call(d):
                    d._dag_fn = node  # noqa: SLF001
    dag_calls = dags  # ast.walk visits each node once: no duplicates

    for call in dag_calls:
        label = getattr(call, "_dag_fn", None)
        label = label.name if label else (ast.literal_eval(call.args[0]) if call.args and isinstance(call.args[0], ast.Constant)
                                          else (kw(call, "dag_id").value if isinstance(kw(call, "dag_id"), ast.Constant) else "?"))
        sd = kw(call, "start_date")
        da = kw(call, "default_args")
        da_node = names.get(da.id) if isinstance(da, ast.Name) else da
        da_keys = dict_keys(da_node) if da_node is not None else set()
        if sd is None and da_node is not None and isinstance(da_node, ast.Dict):
            for k, v in zip(da_node.keys, da_node.values):
                if isinstance(k, ast.Constant) and k.value == "start_date":
                    sd = v
        if sd is not None:
            for c in ast.walk(sd):
                if isinstance(c, ast.Call) and (dotted(c.func) in NOW_CALLS or dotted(c.func).endswith("days_ago")):
                    out.append(finding("AF02", "high", f"DAG '{label}': start_date is computed at parse time "
                                       f"({dotted(c.func)}). It moves on every parse: runs get skipped or "
                                       "duplicated. Use a fixed date", c, path))
                    break
        if kw(call, "catchup") is None:
            out.append(finding("AF03", "warn", f"DAG '{label}': catchup not set. The default differs by version "
                               "(True in Airflow 2, False in 3) — set it explicitly", call, path))
        if kw(call, "schedule_interval") is not None:
            out.append(finding("AF07", "warn", f"DAG '{label}': schedule_interval is deprecated and removed in "
                               "Airflow 3 — use schedule=", call, path))
        if da_keys is not None and "retries" not in (da_keys or set()):
            out.append(finding("AF04", "info", f"DAG '{label}': no retries in default_args (tasks may set their own)",
                               call, path))
        if da_keys is not None and "execution_timeout" not in (da_keys or set()):
            out.append(finding("AF05", "info", f"DAG '{label}': no execution_timeout in default_args: a hung "
                               "task holds its slot forever", call, path))

    # ---- parse-time work: module level, `with DAG` blocks and @dag bodies all run on every
    # scheduler parse; nested def/class/lambda bodies (task code) only run when the task runs ----
    stack = list(tree.body) + [s for c in dag_calls if getattr(c, "_dag_fn", None) for s in c._dag_fn.body]
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(n, ast.Call) and HEAVY.match(dotted(n.func)):
            out.append(finding("AF01", "high", f"parse-time call {dotted(n.func)}(): runs every time the scheduler "
                               "parses the file (every ~30 s). Move it inside a task", n, path))
        stack.extend(ast.iter_child_nodes(n))

    # ---- inside task code: @task functions and python_callable targets ----
    callables = {k.value.id for c in ast.walk(tree) if isinstance(c, ast.Call)
                 for k in c.keywords if k.arg == "python_callable" and isinstance(k.value, ast.Name)}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or getattr(fn, "_dag_fn", None):
            continue
        is_task = fn.name in callables or any("task" in dotted(d) for d in fn.decorator_list)
        if not is_task:
            continue
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and dotted(c.func) in NOW_CALLS:
                out.append(finding("AF06", "warn", f"task '{fn.name}' uses {dotted(c.func)}(): re-runs and backfills "
                                   "compute a different period. Use data_interval_start/end", c, path))

    # ---- sensors, secrets, old imports ----
    for c in ast.walk(tree):
        if isinstance(c, ast.Call) and SENSOR.search(dotted(c.func).split(".")[-1]):
            mode, deferrable = kw(c, "mode"), kw(c, "deferrable")
            if not (isinstance(mode, ast.Constant) and mode.value == "reschedule") and \
                    not (isinstance(deferrable, ast.Constant) and deferrable.value is True):
                out.append(finding("AF11", "info", f"{dotted(c.func)} in poke mode holds a worker slot while it waits: "
                                   "use mode='reschedule' or deferrable=True", c, path))
        if isinstance(c, (ast.Assign, ast.AnnAssign)):
            targets = c.targets if isinstance(c, ast.Assign) else [c.target]
            for t in targets:
                tn = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else ""
                if tn and SECRET_NAME.search(tn) and not SECRET_REF_NAME.search(tn) \
                        and isinstance(c.value, ast.Constant) and isinstance(c.value.value, str) \
                        and secret_like(c.value.value):
                    out.append(finding("AF08", "high", f"'{tn}' is a hard-coded string (value not shown). Use an "
                                       "Airflow connection or a secrets backend; rotate it", c, path))
        if isinstance(c, ast.keyword) and c.arg and SECRET_NAME.search(c.arg) and not SECRET_REF_NAME.search(c.arg) \
                and isinstance(c.value, ast.Constant) and isinstance(c.value.value, str) and secret_like(c.value.value):
            out.append(finding("AF08", "high", f"argument '{c.arg}' is a hard-coded string (value not shown). Use a "
                               "connection or a secrets backend; rotate it", c.value, path))
        if isinstance(c, ast.Dict):
            for k, v in zip(c.keys, c.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and SECRET_NAME.search(k.value) \
                        and not SECRET_REF_NAME.search(k.value) and isinstance(v, ast.Constant) \
                        and isinstance(v.value, str) and secret_like(v.value):
                    out.append(finding("AF08", "high", f"key '{k.value}' holds a hard-coded string (value not shown). "
                                       "Use a connection or a secrets backend; rotate it", v, path))
        if isinstance(c, ast.ImportFrom) and c.module and re.match(
                r"airflow\.(operators|sensors|hooks|contrib)\.\w+_(operator|sensor|hook)$|airflow\.contrib", c.module):
            out.append(finding("AF12", "info", f"import from {c.module}: Airflow 1.x path, removed in 2.x/3.x", c, path))
        elif isinstance(c, ast.ImportFrom) and c.module and AIRFLOW2_PATH.match(c.module):
            out.append(finding("AF13", "info", f"import from {c.module}: deprecated in Airflow 3, use airflow.sdk "
                               "(dag, task, DAG, BaseOperator) or airflow.providers.standard (operators, sensors)",
                               c, path))

    out.sort(key=lambda f: (SEVERITY[f["severity"]], f["line"], f["rule"]))
    return {"file": path, "dags": len(dag_calls), "findings": out}


def collect(target):
    if os.path.isdir(target):
        return sorted(os.path.join(r, f) for r, _, fs in os.walk(target) for f in fs if f.endswith(".py"))
    return [target]


def render(results) -> str:
    L, counts = [], {}
    for r in results:
        if r.get("error"):
            L.append(f"{r['file']}: {r['error']}")
            continue
        L.append(f"{r['file']}  ·  {r['dags']} DAG(s)")
        for f in r["findings"]:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
            L.append(f"  {f['severity'].upper():<5} {f['rule']}  line {f['line']}: {f['message']}")
        if not r["findings"]:
            L.append("  no findings")
    errs = sum(1 for r in results if r.get("error"))
    L += ["", f"SUMMARY  {len(results)} file(s), {errs} unparseable · "
          + (", ".join(f"{counts[k]} {k}" for k in SEVERITY if k in counts) or "no findings")
          + "  ·  static review: the file was never imported or run (NOT_VERIFIED in Airflow)"]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--fail-on", choices=["high", "warn"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.exists(a.path):
        print(f"not found: {a.path}", file=sys.stderr)
        return _io.EXIT_READ_ERROR
    results = [check_file(p) for p in collect(a.path)]
    if a.json:
        _io.emit_json({"files": results})
    else:
        print(render(results))
    if any(r.get("error", "").startswith("syntax") for r in results):
        return _io.EXIT_PARSE_ERROR
    if any(r.get("error") for r in results):
        return _io.EXIT_READ_ERROR
    sev = [SEVERITY[f["severity"]] for r in results for f in r.get("findings", [])]
    if a.fail_on and sev and min(sev) <= SEVERITY[a.fail_on]:
        return _io.EXIT_FINDINGS
    return 0


if __name__ == "__main__":
    sys.exit(main())
