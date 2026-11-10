"""R-semantics helpers for the Python port of the R referee (methodology/contracts.R,
workflow-gate/workflow_gate.R, procedure-gate/procedure_gate.R).

The gates must give the same verdict as the R gate, so the port reproduces the R
behaviour the checks depend on: jsonlite parsing, `$` partial matching, `identical()`,
`as.character()` / `as.numeric()` coercion, `&&` scalar rules, and the places where R
raises an error (which the R contract turns into a "well-formed contract" FAIL).

Value model (what jsonlite gives with simplifyVector = FALSE):
  None  -> NULL            dict -> named list        list -> unnamed list
  str / int / float / bool -> length-1 atomic vector
  RVec  -> any other atomic vector (length 0, >1, NA, or produced by simplification)
  DataFrame -> data.frame (only from simplifyVector = TRUE)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re

__all__ = []


class RError(Exception):
    """An R runtime error. Callers that wrap R tryCatch() catch exactly this."""


class RVec:
    """Atomic vector. type in {'lgl','int','dbl','chr'}; None marks NA."""
    __slots__ = ("type", "v")

    def __init__(self, type_, values):
        self.type = type_
        self.v = list(values)

    def __repr__(self):
        return f"RVec({self.type}, {self.v!r})"


class DataFrame:
    __slots__ = ("cols", "nrow", "dup_names")

    def __init__(self, cols, nrow):
        self.cols = dict(cols)  # name -> RVec | list (list column)
        self.nrow = nrow
        self.dup_names = False

    def __repr__(self):
        return f"DataFrame({self.nrow} rows, {list(self.cols)})"


# ---------------------------------------------------------------- type predicates

def is_null(x):
    return x is None


def _scalar_type(x):
    if isinstance(x, bool):
        return "lgl"
    if isinstance(x, int):
        return "int"
    if isinstance(x, float):
        return "dbl"
    if isinstance(x, str):
        return "chr"
    return None


def atomic_type(x):
    if isinstance(x, RVec):
        return x.type
    return _scalar_type(x)


def is_list(x):
    return isinstance(x, (dict, list, DataFrame))


def is_data_frame(x):
    return isinstance(x, DataFrame)


def is_character(x):
    return atomic_type(x) == "chr"


def is_logical(x):
    return atomic_type(x) == "lgl"


def is_numeric(x):
    return atomic_type(x) in ("int", "dbl")


def length(x):
    if x is None:
        return 0
    if isinstance(x, RVec):
        return len(x.v)
    if isinstance(x, (dict, list)):
        return len(x)
    if isinstance(x, DataFrame):
        return len(x.cols)
    return 1


def names(x):
    """names(x); None for NULL names."""
    if isinstance(x, dict):
        return list(x.keys())
    if isinstance(x, DataFrame):
        return list(x.cols.keys())
    return None


def has_names_null(x):
    return names(x) is None


def values(x):
    """Atomic values as a python list (None = NA). Scalars become 1-lists."""
    if x is None:
        return []
    if isinstance(x, RVec):
        return list(x.v)
    t = _scalar_type(x)
    if t is not None:
        return [x]
    raise RError("not an atomic vector")


def elements(x):
    """What lapply/vapply/for iterate over, as R values."""
    if x is None:
        return []
    if isinstance(x, dict):
        return list(x.values())
    if isinstance(x, list):
        return list(x)
    if isinstance(x, DataFrame):
        return list(x.cols.values())
    if isinstance(x, RVec):
        return [v if v is not None else RVec(x.type, [None]) for v in x.v]
    return [x]


def scalar_na(x):
    """is.na() for a length-1 value."""
    if isinstance(x, RVec):
        return len(x.v) == 1 and x.v[0] is None
    if isinstance(x, float) and math.isnan(x):
        return True
    return False


# ---------------------------------------------------------------- access

def dollar(x, name):
    """R `x$name` (partial matching on lists, error on atomic vectors)."""
    if x is None:
        return None
    if isinstance(x, dict):
        if name in x:
            return x[name]
        hits = [k for k in x if k.startswith(name)]
        return x[hits[0]] if len(hits) == 1 else None
    if isinstance(x, list):
        return None
    if isinstance(x, DataFrame):
        if name in x.cols:
            return x.cols[name]
        hits = [k for k in x.cols if k.startswith(name)]
        return x.cols[hits[0]] if len(hits) == 1 else None
    raise RError("$ operator is invalid for atomic vectors")


def D(x, *path):
    """Chained `$` access: D(s3, 'methodology', 'operational')."""
    for p in path:
        x = dollar(x, p)
    return x


def elt(x, name):
    """R `x[[name]]` with exact matching; `x[[i]]` for an int (1-based)."""
    if isinstance(name, int) and not isinstance(name, bool):
        if isinstance(x, (list, dict)):
            vals = list(x.values()) if isinstance(x, dict) else x
            if 1 <= name <= len(vals):
                return vals[name - 1]
            raise RError("subscript out of bounds")
        vs = values(x)
        if 1 <= name <= len(vs):
            return vs[name - 1]
        raise RError("subscript out of bounds")
    if x is None:
        return None
    if isinstance(x, dict):
        return x.get(name)
    if isinstance(x, list):
        return None
    if isinstance(x, DataFrame):
        return x.cols.get(name)
    raise RError("subscript out of bounds")


# ---------------------------------------------------------------- coercion

def num2str(x: float) -> str:
    """as.character(<double>) as R >= 4.3 prints it (15 significant digits, R's fixed/sci choice)."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0"
    s = None
    for digits in range(1, 16):
        cand = f"{x:.{digits}g}"
        if float(cand) == float(f"{x:.15g}"):
            s = cand
            sig = digits
            break
    if s is None:
        s = f"{x:.15g}"
        sig = 15
    if float(f"{x:.15g}") != x and abs(x) >= 1e15 and float(x).is_integer():
        # R >= 4.3: 15 significant digits, except integer-valued numbers >= 1e15, which are given exactly
        for digits in range(16, 18):
            cand = f"{x:.{digits}g}"
            if float(cand) == x:
                sig = digits
                break
        else:
            sig = 17
    mant_exp = f"{abs(x):.{sig - 1}e}"
    mant, exp = mant_exp.split("e")
    e = int(exp)
    mant = mant.rstrip("0").rstrip(".") if "." in mant else mant
    sig = len(mant.replace(".", ""))
    neg = "-" if x < 0 else ""
    sci = f"{neg}{mant}e{'+' if e >= 0 else '-'}{abs(e):02d}"
    if e >= 0:
        dec = max(0, sig - e - 1)
        fixed_w = e + 1 + (1 + dec if dec else 0)
    else:
        dec = sig - e - 1
        fixed_w = 1 + 1 + dec
    fixed_w += len(neg)
    if fixed_w <= len(sci):
        if abs(x) >= 1e15 and float(x).is_integer():
            return f"{x:.0f}"
        return f"{x:.{dec}f}" if dec else f"{x:.0f}"
    return sci


def _scalar_as_character(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return num2str(v)
    if isinstance(v, str):
        return v
    raise RError("cannot coerce")


def _deparse(x):
    # Only used for as.character(list(<non-scalar>)); R gives e.g. "c(1, 2)" or "list(...)".
    if x is None:
        return "NULL"
    if isinstance(x, RVec):
        vals = ["NA" if v is None else (json.dumps(v) if isinstance(v, str) else _scalar_as_character(v)) for v in x.v]
        return "c(" + ", ".join(vals) + ")" if len(vals) != 1 else vals[0]
    if isinstance(x, (dict, list)):
        return "list(...)"
    return _scalar_as_character(x)


def as_character(x):
    """as.character(x) -> python list of str/None."""
    if x is None:
        return []
    if isinstance(x, (dict, list)):
        out = []
        for e in elements(x):
            if isinstance(e, RVec) and len(e.v) == 1:
                out.append(_scalar_as_character(e.v[0]))
            elif _scalar_type(e) is not None:
                out.append(_scalar_as_character(e))
            else:
                out.append(_deparse(e))
        return out
    if isinstance(x, DataFrame):
        return as_character(list(x.cols.values()))
    return [_scalar_as_character(v) for v in values(x)]


_NUM_RE = re.compile(r"^[+-]?((\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)$")
_HEX_RE = re.compile(r"^[+-]?0[xX][0-9a-fA-F]+$")


def str2num(s):
    """R's as.numeric(<character>) for one string; None = NA."""
    if s is None:
        return None
    t = s.strip(" \t\n\r")
    if t in ("NA",):
        return None
    if _NUM_RE.match(t):
        return float(t)
    if _HEX_RE.match(t):
        return float(int(t, 16))
    low = t.lower().lstrip("+")
    neg = t.startswith("-")
    if neg:
        low = low[1:]
    if t in ("NaN", "+NaN", "-NaN"):
        return float("nan")
    if low in ("inf", "infinity"):
        return float("-inf") if neg else float("inf")
    return None


def as_numeric(x):
    """as.numeric(x) -> python list of float/None."""
    if x is None:
        return []
    if isinstance(x, (dict, list)):
        out = []
        for e in elements(x):
            if e is None or length(e) != 1 or is_list(e):
                raise RError("'list' object cannot be coerced to type 'double'")
            out.extend(as_numeric(e))
        return out
    if isinstance(x, DataFrame):
        raise RError("'list' object cannot be coerced to type 'double'")
    out = []
    t = atomic_type(x)
    for v in values(x):
        if v is None:
            out.append(None)
        elif t == "chr":
            out.append(str2num(v))
        else:
            out.append(float(v))
    return out


def lgl1(x, what="x"):
    """Coerce an operand of && / || / if() to a single TRUE/FALSE/None(NA), raising like R."""
    if isinstance(x, bool):
        return x
    if x is None or isinstance(x, (dict, list, DataFrame)) or atomic_type(x) == "chr":
        raise RError(f"invalid '{what}' type in 'x && y'")
    vs = values(x)
    if len(vs) > 1:
        raise RError(f"'length = {len(vs)}' in coercion to 'logical(1)'")
    if len(vs) == 0:
        return None
    v = vs[0]
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return bool(v)


def AND(*thunks):
    """R `a && b && ...` with lazy operands (pass callables or values). Returns True/False/None(NA)."""
    result = True
    for i, t in enumerate(thunks):
        v = lgl1(t() if callable(t) else t, "x" if i == 0 else "y")
        if v is False:
            return False
        if v is None:
            result = None
    return result


def OR(*thunks):
    result = False
    for i, t in enumerate(thunks):
        v = lgl1(t() if callable(t) else t, "x" if i == 0 else "y")
        if v is True:
            return True
        if v is None:
            result = None
    return result


def NOT(x):
    """R `!x` for a scalar logical result (None = NA)."""
    if x is None:
        return None
    return not x


def r_if(x):
    """Condition of R `if`: errors on NA / length != 1."""
    v = lgl1(x, "x") if not isinstance(x, bool) else x
    if v is None:
        raise RError("missing value where TRUE/FALSE needed")
    return v


def is_true(x):
    """isTRUE(x)."""
    if isinstance(x, bool):
        return x
    if isinstance(x, RVec) and x.type == "lgl" and len(x.v) == 1:
        return x.v[0] is True
    return False


# ---------------------------------------------------------------- identical / vectors

def identical(a, b):
    if a is None or b is None:
        return a is None and b is None
    ta, tb = atomic_type(a), atomic_type(b)
    if ta is not None or tb is not None:
        if ta != tb:
            return False
        va, vb = values(a), values(b)
        if len(va) != len(vb):
            return False
        for x, y in zip(va, vb):
            if x is None or y is None:
                if not (x is None and y is None):
                    return False
            elif isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y):
                continue
            elif x != y:
                return False
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a.keys()) == list(b.keys()) and all(identical(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(identical(x, y) for x, y in zip(a, b))
    if isinstance(a, DataFrame) and isinstance(b, DataFrame):
        return a.nrow == b.nrow and list(a.cols) == list(b.cols) and all(identical(a.cols[k], b.cols[k]) for k in a.cols)
    # dict {} vs list [] etc.
    return False


def unlist(x):
    """unlist(x) -> (values list, type) with R coercion (lgl < int < dbl < chr). None type for NULL."""
    flat = []

    def walk(e):
        if e is None:
            return
        if isinstance(e, (dict, list)):
            for c in elements(e):
                walk(c)
            return
        if isinstance(e, DataFrame):
            for c in e.cols.values():
                walk(c)
            return
        t = atomic_type(e)
        for v in values(e):
            flat.append((t, v))

    walk(x)
    if not flat:
        return [], None
    order = ["lgl", "int", "dbl", "chr"]
    top = max((t for t, _ in flat), key=order.index)
    out = []
    for t, v in flat:
        if v is None:
            out.append(None)
        elif top == "chr":
            out.append(_scalar_as_character(v))
        elif top == "dbl":
            out.append(float(v))
        elif top == "int":
            out.append(int(v))
        else:
            out.append(v)
    return out, top


def unlist_values(x):
    return unlist(x)[0]


def _match_key(v, as_chr):
    if v is None:
        return ("NA",)
    if as_chr:
        return ("s", _scalar_as_character(v))
    if isinstance(v, float) and math.isnan(v):
        return ("nan",)
    if isinstance(v, bool):
        return ("n", float(v))
    if isinstance(v, (int, float)):
        return ("n", float(v))
    return ("s", v)


def _vec(x):
    """(values, type) for an R value used as a vector in %in% / setequal / unique."""
    if isinstance(x, (dict, list, DataFrame)):
        # match() on lists works element-wise on length-1 elements; approximate by unlist
        return unlist(x)
    if x is None:
        return [], None
    return values(x), atomic_type(x)


def in_(x, table):
    """x %in% table -> list of bool."""
    xv, xt = _vec(x)
    tv, tt = _vec(table)
    as_chr = "chr" in (xt, tt)
    keys = {_match_key(v, as_chr) for v in tv}
    return [_match_key(v, as_chr) in keys for v in xv]


def all_(bools):
    """all() over python bool/None list. None = NA."""
    res = True
    for b in bools:
        if b is False:
            return False
        if b is None:
            res = None
    return res


def any_(bools):
    res = False
    for b in bools:
        if b is True:
            return True
        if b is None:
            res = None
    return res


def setequal(x, y):
    xv, xt = _vec(x)
    yv, yt = _vec(y)
    as_chr = "chr" in (xt, yt)
    return {_match_key(v, as_chr) for v in xv} == {_match_key(v, as_chr) for v in yv}


def any_duplicated(x):
    xv, xt = _vec(x)
    seen = set()
    for v in xv:
        k = _match_key(v, xt == "chr")
        if k in seen:
            return True
        seen.add(k)
    return False


def any_na(x):
    """anyNA(x) (recursive = FALSE: list elements count only if length-1 NA)."""
    if x is None:
        return False
    if isinstance(x, DataFrame):
        return any(any_na(c) for c in x.cols.values())
    if isinstance(x, (dict, list)):
        return any(isinstance(e, RVec) and len(e.v) == 1 and e.v[0] is None or (isinstance(e, float) and math.isnan(e)) for e in elements(x))
    return any(v is None or (isinstance(v, float) and math.isnan(v)) for v in values(x))


def trimws(s):
    return s.strip(" \t\r\n")


def nzchar(s):
    return len(s) > 0


# ---------------------------------------------------------------- JSON (jsonlite)

def _parse_int(s):
    v = int(s)
    if s.lstrip("-") == "0" and s.startswith("-"):
        return 0
    if abs(v) > 2147483647:
        return float(v)
    return v


def _reject_constant(name):
    raise ValueError(f"invalid JSON constant {name}")


def _first_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k not in d:  # R `$` and `[[` return the first of duplicated names
            d[k] = v
    return d


def json_loads(text):
    return json.loads(text, parse_int=_parse_int, parse_constant=_reject_constant, object_pairs_hook=_first_pairs)


def read_json_file(path):
    """jsonlite::fromJSON(path, simplifyVector = FALSE); raises RError on any failure."""
    if not os.path.isfile(path):
        raise RError(f"cannot read {path}")
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
        if text.startswith("\ufeff"):
            text = text[1:]
        if not text.strip():
            raise RError("empty JSON")
        return json_loads(text)
    except RError:
        raise
    except Exception as e:  # noqa: BLE001 - mirrors tryCatch(error=)
        raise RError(str(e))


def simplify(x):
    """jsonlite simplifyVector = TRUE (simplifyDataFrame, simplifyMatrix) for the shapes the gates read."""
    if isinstance(x, dict):
        return {k: simplify(v) for k, v in x.items()}
    if isinstance(x, list):
        if len(x) == 0:
            return []
        if all(e is None or _scalar_type(e) is not None for e in x) and any(e is not None for e in x):
            types = {_scalar_type(e) for e in x if e is not None}
            order = ["lgl", "int", "dbl", "chr"]
            top = max(types, key=order.index)
            vals = []
            for e in x:
                if e is None:
                    vals.append(None)
                elif top == "chr":
                    vals.append(_scalar_as_character(e) if not isinstance(e, str) else e)
                elif top == "dbl":
                    vals.append(float(e))
                elif top == "int":
                    vals.append(int(e))
                else:
                    vals.append(e)
            if len(vals) == 1 and vals[0] is not None:
                return vals[0]
            return RVec(top, vals)
        if all(e is None for e in x):
            return RVec("lgl", [None] * len(x))
        if all(isinstance(e, dict) for e in x) and any(len(e) for e in x):
            keys = []
            for e in x:
                for k in e:
                    if k not in keys:
                        keys.append(k)
            cols = {}
            for k in keys:
                col = [e.get(k) for e in x]
                if all(c is None or _scalar_type(c) is not None for c in col):
                    s = simplify(col) if any(c is not None for c in col) else RVec("lgl", [None] * len(col))
                    if not isinstance(s, RVec):
                        s = RVec(_scalar_type(s), [s])
                    cols[k] = s
                else:
                    cols[k] = [simplify(c) for c in col]
            return DataFrame(cols, len(x))
        return [simplify(e) for e in x]
    return x


# ---------------------------------------------------------------- files

def sha256_file(path):
    if not os.path.isfile(path):
        raise RError(f"The file does not exist: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def r_strsplit_slash(path):
    parts = path.split("/")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def normalize_path(p):
    return os.path.realpath(p)


def file_exists(p):
    return os.path.exists(p)


def dir_exists(p):
    return os.path.isdir(p)


def file_size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return None
