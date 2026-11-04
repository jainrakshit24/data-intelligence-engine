"""Shared plumbing for the data-intelligence-engine scripts.

Every script reads data through this module so that the safety rules live in
one place: the user's file is opened read-only through DuckDB, raw values are
never printed by default, extensions are never downloaded silently, and every
result carries a coverage block.
"""
from __future__ import annotations

import atexit
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Optional

EXIT_USAGE = 2
EXIT_NO_DUCKDB = 3
EXIT_EXTENSION_REQUIRED = 4
EXIT_READ_ERROR = 5
EXIT_PARSE_ERROR = 6
EXIT_FINDINGS = 1  # --fail-on threshold reached

# Above this file size, non-key distinct counts and quantiles switch to
# approximate algorithms. Every approximate figure is marked "≈" in output.
EXACT_BYTES_LIMIT = 1 << 30  # 1 GiB

PLACEHOLDERS = [
    "n/a", "na", "null", "none", "nil", "-", "--", "?", "unknown", "unk",
    "missing", "nan", "#n/a", "undefined", "tbd", "not available",
]

DATE_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y",
]

# Regexes are written for DuckDB (RE2). They match anywhere in the value, so a
# free-text column that merely contains an email is still counted.
PII_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone": r"(^|[^0-9])\+?[0-9][0-9 ().-]{8,}[0-9]([^0-9]|$)",
    "ipv4": r"(^|[^0-9])([0-9]{1,3}\.){3}[0-9]{1,3}([^0-9]|$)",
    "card_like": r"(^|[^0-9])([0-9][ -]?){13,19}([^0-9]|$)",
}

PII_NAME_HINTS = re.compile(
    r"(^|_)(e?mail|phone|mobile|msisdn|first_?name|last_?name|full_?name|"
    r"customer_?name|name|address|street|dob|birth|ssn|aadhaar|aadhar|pan|"
    r"passport|ip|ip_?address|"
    # account identifiers point at one person as surely as a name does
    r"customer_?id|user_?id|account_?(id|no|number)|member_?id|client_?id|"
    r"patient_?id|employee_?id|emp_?id|student_?id)($|_)",
    re.I,
)
QUASI_NAME_HINTS = re.compile(r"(^|_)(zip|postcode|postal|pincode|gender|sex|age)($|_)", re.I)
KEY_NAME_HINTS = re.compile(r"(^id$|_id$|_key$|_no$|_number$|^uuid$|_uuid$)", re.I)

INJECTION_PATTERN = (
    r"(?i)(ignore (all |any )?(previous|prior|above) instructions|"
    r"disregard (all |the )?(previous|prior|above)|you are now|system prompt|"
    r"<\s*/?\s*(system|assistant|instructions)\s*>|rm\s+-rf|drop\s+table|"
    r"delete\s+from)"
)

# Words that a user-supplied rule expression may never contain. Expressions are
# spliced into SQL, so this stops a rules file from reading or writing files,
# loading extensions or running a second statement.
FORBIDDEN_IN_EXPRESSIONS = re.compile(
    r";|--|/\*|\b(read_\w+|copy|attach|detach|install|load|pragma|export|"
    r"import|set|reset|call|create|drop|alter|insert|update|delete|getenv|"
    r"glob|sniff_csv|parquet_\w+|query|query_table)\b",
    re.I,
)


# --------------------------------------------------------------------------- #
# DuckDB
# --------------------------------------------------------------------------- #

def require_duckdb():
    """Import duckdb or stop with the exact install command (never silently)."""
    try:
        import duckdb  # noqa: F401
    except ImportError:
        print(
            "ERROR: duckdb is not installed, so this script cannot run.\n"
            "Install it with:  pip install duckdb\n"
            "(The skill does not fall back to reading the file directly: that "
            "would load raw rows into the agent's context.)",
            file=sys.stderr,
        )
        sys.exit(EXIT_NO_DUCKDB)
    return duckdb


MEMORY_LIMIT = os.environ.get("DIE_MEMORY_LIMIT", "1GB")


def connect():
    duckdb = require_duckdb()
    con = duckdb.connect(database=":memory:")
    # Never download an extension as a side effect (rule: disclose first).
    con.execute("SET autoinstall_known_extensions = false")
    # Exact distinct counts hold every unique value, so memory would otherwise
    # grow with cardinality rather than file size. Cap it and let DuckDB spill
    # to a private temp dir (its default would litter the user's working dir).
    spill = tempfile.mkdtemp(prefix="die-spill-")
    atexit.register(shutil.rmtree, spill, ignore_errors=True)
    con.execute(f"SET memory_limit = {lit(MEMORY_LIMIT)}")
    con.execute(f"SET temp_directory = {lit(spill)}")
    return con


def q(name: str) -> str:
    """Quote an identifier."""
    return '"' + name.replace('"', '""') + '"'


def lit(value: str) -> str:
    """Quote a string literal."""
    return "'" + value.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

class ExtensionRequired(Exception):
    pass


@dataclass
class Source:
    path: str
    fmt: str
    files: list
    bytes: int
    sheet: Optional[str] = None
    sheets: list = field(default_factory=list)
    sheet_rows: dict = field(default_factory=dict)
    sample_rows: Optional[int] = None

    @property
    def approximate(self) -> bool:
        return self.bytes > EXACT_BYTES_LIMIT


def detect_format(path: str) -> str:
    p = path.lower()
    for ext, fmt in ((".csv", "csv"), (".tsv", "csv"), (".txt", "csv"),
                     (".jsonl", "json"), (".ndjson", "json"), (".json", "json"),
                     (".parquet", "parquet"), (".pq", "parquet"),
                     (".xlsx", "xlsx")):
        if p.endswith(ext) or p.endswith(ext + ".gz"):
            return fmt
    return "csv"


def xlsx_sheets(path: str):
    """List sheet names and their declared row extent without reading cell data.

    Uses only the zip container, so no extension download is needed to know
    what a workbook holds.
    """
    names, rows = [], {}
    with zipfile.ZipFile(path) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
        names = re.findall(r'<sheet[^>]*\bname="([^"]+)"', wb)
        for i, name in enumerate(names, start=1):
            member = f"xl/worksheets/sheet{i}.xml"
            if member not in z.namelist():
                continue
            with z.open(member) as f:
                head = f.read(4096).decode("utf-8", "replace")
            m = re.search(r'<dimension ref="[A-Z]+\d+:?[A-Z]*(\d*)"', head)
            if m and m.group(1):
                rows[name] = int(m.group(1))
    return names, rows


def open_source(path: str, sheet: Optional[str] = None,
                sample_rows: Optional[int] = None) -> Source:
    files = sorted(glob.glob(path)) if any(c in path for c in "*?[") else [path]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        print(f"ERROR: no file found at {path}", file=sys.stderr)
        sys.exit(EXIT_READ_ERROR)
    fmt = detect_format(files[0])
    src = Source(path=path, fmt=fmt, files=files,
                 bytes=sum(os.path.getsize(f) for f in files),
                 sheet=sheet, sample_rows=sample_rows)
    if fmt == "xlsx":
        src.sheets, src.sheet_rows = xlsx_sheets(files[0])
        if src.sheet is None and src.sheets:
            src.sheet = src.sheets[0]
    return src


def relation_sql(src: Source) -> str:
    paths = src.files[0] if len(src.files) == 1 else "[" + ", ".join(lit(f) for f in src.files) + "]"
    target = lit(paths) if len(src.files) == 1 else paths
    if src.fmt == "csv":
        return f"read_csv({target}, all_varchar = true, header = true, union_by_name = true)"
    if src.fmt == "json":
        return f"read_json_auto({target}, union_by_name = true)"
    if src.fmt == "parquet":
        return f"read_parquet({target}, union_by_name = true)"
    if src.fmt == "xlsx":
        return f"read_xlsx({target}, sheet = {lit(src.sheet)}, all_varchar = true)"
    raise ValueError(src.fmt)


def ensure_extension(con, src: Source, allow_download: bool):
    if src.fmt != "xlsx":
        return
    try:
        con.execute("LOAD excel")
        return
    except Exception:
        pass
    if not allow_download:
        raise ExtensionRequired(
            "Reading .xlsx needs DuckDB's 'excel' extension, which is not installed.\n"
            "Installing it DOWNLOADS code from extensions.duckdb.org into ~/.duckdb/.\n"
            "Re-run with --allow-extension-download to permit that, or export the "
            "sheet to CSV first."
        )
    con.execute("INSTALL excel")
    con.execute("LOAD excel")


def create_view(con, src: Source, allow_download: bool = False, name: str = "src"):
    """Create a view (default `src`) over the data and return its column list."""
    ensure_extension(con, src, allow_download)
    rel = relation_sql(src)
    sample = ""
    if src.sample_rows:
        sample = f" USING SAMPLE reservoir({int(src.sample_rows)} ROWS) REPEATABLE (42)"
    try:
        con.execute(f"CREATE VIEW {q(name)} AS SELECT * FROM {rel}{sample}")
        cols = con.execute(f"DESCRIBE {q(name)}").fetchall()
    except Exception as e:  # malformed file, unreadable sheet, ...
        print(f"ERROR: could not read {src.path}: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(EXIT_READ_ERROR)
    return [(c[0], c[1]) for c in cols]


def total_rows(con, src: Source) -> int:
    if not src.sample_rows:
        return con.execute("SELECT count(*) FROM src").fetchone()[0]
    return con.execute(f"SELECT count(*) FROM {relation_sql(src)}").fetchone()[0]


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #

@dataclass
class Coverage:
    rows_read: int
    rows_total: int
    files_ok: int
    files_total: int
    strategy: str
    sheets_read: list = field(default_factory=list)
    sheets_total: list = field(default_factory=list)
    filters: list = field(default_factory=list)
    approximations: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def line(self) -> str:
        parts = [f"{self.rows_read:,}/{self.rows_total:,} rows",
                 f"{self.files_ok}/{self.files_total} files"]
        if self.sheets_total:
            unread = [s for s in self.sheets_total if s not in self.sheets_read]
            parts.append(f"sheets {len(self.sheets_read)}/{len(self.sheets_total)} read"
                         + (f" (not read: {', '.join(unread)})" if unread else ""))
        parts.append(f"strategy: {self.strategy}")
        parts.append("filters: " + ("; ".join(self.filters) if self.filters else "none"))
        if self.approximations:
            parts.append("approximate: " + "; ".join(self.approximations))
        return "COVERAGE: " + " · ".join(parts)


def coverage_for(src: Source, rows_read: int, rows_total: int) -> Coverage:
    if src.sample_rows:
        strategy = f"sample (reservoir {rows_read:,} rows, seed 42) — every statistic is an ESTIMATE"
    else:
        strategy = (f"whole (streamed by DuckDB; its working memory is capped at {MEMORY_LIMIT} "
                    "and spills to a temp dir beyond that)")
    cov = Coverage(rows_read=rows_read, rows_total=rows_total,
                   files_ok=len(src.files), files_total=len(src.files),
                   strategy=strategy)
    if src.fmt == "xlsx":
        cov.sheets_read = [src.sheet] if src.sheet else []
        cov.sheets_total = list(src.sheets)
        for name, n in src.sheet_rows.items():
            if n >= 1_048_576:
                cov.notes.append(
                    f"sheet '{name}' declares {n:,} rows = the Excel row ceiling: "
                    "treat as possibly truncated upstream")
    if src.approximate:
        cov.approximations.append(
            f"file is {src.bytes / (1 << 30):.1f} GiB > 1 GiB: non-key distinct "
            "counts and quantiles use approximate algorithms (marked ≈)")
    return cov


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def sheets_line(sheets, sheet_rows) -> str:
    """One line listing a workbook's sheets, flagging any at the Excel row ceiling."""
    parts = []
    for s in sheets:
        n = sheet_rows.get(s)
        tag = f"~{n:,} rows" if n else "rows unknown"
        if n and n >= 1_048_576:
            tag += " = Excel's row ceiling: possibly TRUNCATED upstream"
        parts.append(f"{s} ({tag})")
    return "Sheets (read from the zip, no download): " + ", ".join(parts)


def mask(value) -> str:
    """Mask a single value so it can be shown without revealing it."""
    s = str(value)
    if "@" in s:
        user, _, domain = s.partition("@")
        return (user[:1] + "***@" + domain) if user else "***@" + domain
    if len(s) <= 2:
        return "*" * len(s)
    return s[:1] + "*" * min(len(s) - 2, 6) + s[-1:]


def pct(part: float, whole: float, digits: int = 1) -> str:
    if not whole:
        return "n/a"
    return f"{100.0 * part / whole:.{digits}f}%"


def emit_json(obj) -> None:
    def default(o):
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        return str(o)
    print(json.dumps(obj, indent=2, default=default, ensure_ascii=False))


def check_expression(expr: str) -> Optional[str]:
    """Return an error message if a user rule expression is unsafe, else None."""
    if FORBIDDEN_IN_EXPRESSIONS.search(expr):
        return ("expression rejected: it contains a statement separator, comment "
                "or a function/keyword that could touch files or the database")
    return None
