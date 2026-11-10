"""SELECT-only enforcement and execution for the SQL Analyst's source gates (G3S).

Two independent layers:
1. Static lint: comments and string literals are stripped; exactly one statement; it starts with SELECT or WITH;
   no write/DDL/session keyword anywhere (INSERT, UPDATE, DELETE, ..., INTO, PRAGMA, ATTACH, ...).
2. Execution (sqlite engine): the snapshot is opened read-only (mode=ro, immutable when its hash is pinned), with
   query_only on and an authorizer that denies every action except reads, selects, functions and recursive CTEs.
Other engines need an executor passed in by the caller; without one the gate is TOOL_ERROR, never PASS.
"""
from __future__ import annotations

import re
import sqlite3

FORBIDDEN = ["INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "REPLACE", "CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT",
             "REVOKE", "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "ANALYZE", "COPY", "CALL", "EXEC", "EXECUTE",
             "INTO", "SET", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "LOCK", "UNLOAD", "EXPORT", "IMPORT",
             "LOAD", "INSTALL", "USE", "DECLARE", "PREPARE", "DEALLOCATE", "LISTEN", "NOTIFY", "REFRESH", "COMMENT",
             "RENAME", "OPTIMIZE", "PUT", "GET", "REMOVE"]


def strip_sql(sql):
    """Remove comments and quoted literals/identifiers; raises ValueError on an unterminated one."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            out.append(" ")
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise ValueError("unterminated block comment")
            i = j + 2
            out.append(" ")
        elif c in ("'", '"', "`") or c == "[":
            close = "]" if c == "[" else c
            j = i + 1
            while True:
                j = sql.find(close, j)
                if j < 0:
                    raise ValueError("unterminated quoted literal")
                if close != "]" and sql.startswith(close * 2, j):
                    j += 2
                    continue
                break
            out.append(" '' " if c == "'" else " q ")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def lint(sql):
    """Returns a list of problems; empty means SELECT-only by static inspection."""
    try:
        body = strip_sql(sql)
    except ValueError as e:
        return [str(e)]
    probs = []
    stmts = [s for s in body.split(";") if s.strip()]
    if len(stmts) != 1:
        probs.append(f"exactly one statement required, found {len(stmts)}")
    first = re.match(r"\s*\(*\s*([A-Za-z]+)", body)
    if not first or first.group(1).upper() not in ("SELECT", "WITH"):
        probs.append("statement must start with SELECT or WITH")
    words = {w.upper() for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", body)}
    bad = sorted(words & set(FORBIDDEN))
    if bad:
        probs.append(f"forbidden keywords: {bad}")
    return probs


_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


def _authorizer(action, *_):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def run_sqlite(db_path, sql, max_rows=1000):
    """Execute one SELECT on a read-only snapshot. Returns (columns, rows, total_row_count)."""
    uri = "file:" + db_path.replace("?", "%3f").replace("#", "%23") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("PRAGMA query_only = ON")
        con.set_authorizer(_authorizer)
        cur = con.execute(sql)
        cols = [d[0] for d in (cur.description or [])]
        rows, total = [], 0
        for r in cur:
            total += 1
            if len(rows) < max_rows:
                rows.append(list(r))
        return cols, rows, total
    finally:
        con.close()
