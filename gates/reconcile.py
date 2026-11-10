"""Exact full-field comparison of two CSV outputs (used by G4a fixtures and G4b reconciliation).

Default: every column must match exactly as text (R read.csv colClasses=character, no trimming), keyed by the declared keys.
Only columns the locked design names under `tolerance.fields` may differ, and then only within
absolute_tolerance + relative_tolerance * max(|x|, |y|), with R's numeric-missingness contract.
The ported R m_compare (methodology/contracts.R) is run on the same pair with every non-tolerance column as an exact
field, so this is never looser than the R comparison.
"""
from __future__ import annotations

from gates import methodology as M
from gates.rsem import RError, RVec


def _cols(df):
    return list(df.cols.keys())


def _col(df, name):
    c = df.cols[name]
    return list(c.v) if isinstance(c, RVec) else list(c)


def compare(root, ref_a, ref_b, keys, tolerance=None):
    """Returns (ok, detail dict). ref_* are {path} dicts relative to root."""
    try:
        a = M.m_csv(ref_a, root)
        b = M.m_csv(ref_b, root)
    except (RError, OSError, UnicodeDecodeError) as e:
        return False, {"error": f"unreadable CSV: {e}"}
    tol = tolerance or {}
    tol_fields = list(tol.get("fields") or [])
    ca, cb = _cols(a), _cols(b)
    detail = {"a": ref_a.get("path"), "b": ref_b.get("path"), "rows_a": a.nrow, "rows_b": b.nrow}
    if a.dup_names or b.dup_names or len(set(ca)) != len(ca) or len(set(cb)) != len(cb):
        return False, dict(detail, error="duplicate column names")
    if set(ca) != set(cb):
        return False, dict(detail, error="column sets differ", only_a=sorted(set(ca) - set(cb)), only_b=sorted(set(cb) - set(ca)))
    if not keys or any(k not in ca for k in keys):
        return False, dict(detail, error=f"keys {keys} not all present")
    if any(f not in ca or f in keys for f in tol_fields):
        return False, dict(detail, error="tolerance fields must be non-key columns present in both outputs")
    exact = [c for c in ca if c not in keys and c not in tol_fields]
    plan = {"keys": list(keys), "exact_fields": exact, "numeric_fields": tol_fields,
            "absolute_tolerance": float(tol.get("absolute_tolerance", 0)), "relative_tolerance": float(tol.get("relative_tolerance", 0))}
    if tol.get("numeric_missingness") is not None:
        plan["numeric_missingness"] = tol["numeric_missingness"]
    try:
        r_ok = bool(M.m_compare(a, b, plan))
    except RError as e:
        r_ok = False
        detail["m_compare_error"] = str(e)
    # Independent field-by-field count for the report.
    def index(df):
        rows = {}
        kc = [_col(df, k) for k in keys]
        for i in range(df.nrow):
            key = tuple(c[i] for c in kc)
            if key in rows or any(v is None or str(v).strip() == "" for v in key):
                return None
            rows[key] = i
        return rows
    ia, ib = index(a), index(b)
    if ia is None or ib is None:
        return False, dict(detail, error="keys missing, blank or duplicated", m_compare=r_ok)
    mism = []
    for k in sorted(set(ia) | set(ib)):
        if k not in ia or k not in ib:
            mism.append({"key": list(k), "field": None, "a": "present" if k in ia else "absent", "b": "present" if k in ib else "absent"})
            continue
        for f in exact:
            va, vb = _col(a, f)[ia[k]], _col(b, f)[ib[k]]
            if va != vb:
                mism.append({"key": list(k), "field": f, "a": va, "b": vb})
        for f in tol_fields:
            va, vb = _col(a, f)[ia[k]], _col(b, f)[ib[k]]
            try:
                x, y = float(va), float(vb)
                lim = plan["absolute_tolerance"] + plan["relative_tolerance"] * max(abs(x), abs(y))
                if not (abs(x - y) <= lim):
                    mism.append({"key": list(k), "field": f, "a": va, "b": vb, "tolerance": lim})
            except (TypeError, ValueError):
                if va != vb or "numeric_missingness" not in plan:
                    mism.append({"key": list(k), "field": f, "a": va, "b": vb, "note": "non-numeric under tolerance"})
    detail.update(mismatch_count=len(mism), mismatches=mism[:50], m_compare=r_ok, exact_fields=exact, tolerance_fields=tol_fields)
    return (r_ok and not mism), detail
