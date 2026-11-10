"""Python side of the R/Python parity harness (called from r_prelude.R).

  fn <payload.json>                          run one methodology function on type-tagged R arguments, compare
  gate-py <kind> <framework> <out.json> ...  run the Python gate CLI (workflow | procedure) on the live state
  gate-compare <py.json> <r.json>            compare the Python run with the R run of the same call

Every comparison appends one JSON line to $PARITY_LOG:
  {"kind", "name", "match": true|false|null, "reason", "r", "py"}   (match null = not comparable, counted as skipped)
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import sys
import traceback

from gates import rsem
from gates.rsem import RVec, DataFrame, RError

LOG = os.environ.get("PARITY_LOG", "/tmp/parity.jsonl")
# Details whose wording is an error message from the language runtime (R condition message vs Python message).
ERROR_DETAIL_CHECKS = ("Methodology well-formed contract",)


class Unsupported(Exception):
    pass


_PAYLOAD = None


def log(rec):
    if rec.get("match") is False and _PAYLOAD and os.path.exists(_PAYLOAD):
        import shutil
        keep = LOG + ".payloads"
        os.makedirs(keep, exist_ok=True)
        rec["payload"] = shutil.copy(_PAYLOAD, keep)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


# ------------------------------------------------------------------ type-tagged R values -> port value model

def _atomic(t, vals, na):
    na = {int(i) - 1 for i in (na or [])}
    if t == "dbl":
        out = []
        for i, s in enumerate(vals):
            s = str(s)
            out.append(None if i in na else float("nan") if s in ("NaN", "nan") else float(s.replace("Inf", "inf")))
    elif t == "int":
        out = [None if i in na else int(v) for i, v in enumerate(vals)]
    elif t == "lgl":
        out = [None if i in na else bool(v) for i, v in enumerate(vals)]
    else:
        out = [None if i in na else str(v) for i, v in enumerate(vals)]
    return out


def des(node, top=False):
    t = node["t"]
    if t == "NULL":
        return None
    if t == "unsupported":
        raise Unsupported(node.get("class"))
    if t == "df":
        cols = {}
        names = node["names"]
        if len(set(names)) != len(names):
            raise Unsupported("data.frame with duplicate names")
        for n, c in zip(names, node["cols"]):
            v = des(c)
            if isinstance(v, (dict, DataFrame)):
                raise Unsupported("nested data.frame column")
            if isinstance(v, list):
                cols[n] = v
            elif isinstance(v, RVec):
                cols[n] = v
            else:
                cols[n] = RVec(rsem.atomic_type(v), [v])
        return DataFrame(cols, node["nrow"])
    if t == "list":
        vals = [des(v) for v in node["v"]]
        if node.get("named"):
            names = node["names"]
            if any(n == "" for n in names) or len(set(names)) != len(names):
                raise Unsupported("list with empty or duplicate names")
            return dict(zip(names, vals))
        return vals
    out = _atomic(t, node["v"], node.get("na"))
    if len(out) == 1 and out[0] is not None and not (t == "dbl" and out[0] != out[0]):
        return out[0]
    return RVec(t, out)


def des_call_args(node):
    """list(...) of the R call -> (positional, keyword)."""
    vals = [des(v) for v in node["v"]]
    names = node["names"] if node.get("named") else [""] * len(vals)
    pos, kw = [], {}
    for n, v in zip(names, vals):
        if n:
            kw[n] = v
        else:
            pos.append(v)
    return pos, kw


# ------------------------------------------------------------------ comparison helpers

def norm_checks(x):
    """A check list in either representation -> [(check, result, detail)]."""
    out = []
    for c in (x or []):
        d = c.get("detail")
        if isinstance(d, RVec):
            d = d.v
        out.append((c.get("check"), c.get("result"), d))
    return out


def compare_checks(r, p):
    r, p = norm_checks(r), norm_checks(p)
    if [(c, res) for c, res, _ in r] != [(c, res) for c, res, _ in p]:
        return False, {"r": [(c, res) for c, res, _ in r], "py": [(c, res) for c, res, _ in p]}
    diffs = []
    for (c, res, rd), (_, _, pd) in zip(r, p):
        if c in ERROR_DETAIL_CHECKS or (c and c.endswith("parses") and res == "FAIL"):
            continue
        if _detail(rd) != _detail(pd):
            diffs.append({"check": c, "r": rd, "py": pd})
    return (not diffs), {"detail_diffs": diffs} if diffs else {}


def _detail(d):
    if isinstance(d, list) and len(d) == 1:
        d = d[0]
    if isinstance(d, float) and d.is_integer():
        d = int(d)
    return d


def to_plain(x):
    if isinstance(x, RVec):
        return x.v if len(x.v) != 1 else x.v[0]
    if isinstance(x, DataFrame):
        return {k: to_plain(v) for k, v in x.cols.items()}
    if isinstance(x, dict):
        return {k: to_plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [to_plain(v) for v in x]
    return x


ARG_ALIASES = {"validate_stage_receipt": {"project_root": "root"}}


def _bind(fn, name, pos, kw):
    params = list(inspect.signature(fn).parameters)
    aliases = ARG_ALIASES.get(name, {})
    out = {}
    for k, v in kw.items():
        k = aliases.get(k, k)
        if k not in params:  # R partial argument matching
            cands = [p for p in params if p.startswith(k)]
            if len(cands) != 1:
                raise Unsupported(f"argument {k}")
            k = cands[0]
        out[k] = v
    free = [p for p in params if p not in out]
    for p, v in zip(free, pos):
        out[p] = v
    return out


def run_fn(payload_path):
    global _PAYLOAD
    _PAYLOAD = payload_path
    with open(payload_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    name = payload["fn"]
    rec = {"kind": "fn", "name": name}
    try:
        pos, kw = des_call_args(payload["args"])
        r_res = None if payload.get("error") else des(payload["result"])
    except Unsupported as e:
        rec.update(match=None, reason=f"argument not representable: {e}")
        log(rec)
        return
    from gates import methodology as M
    from gates import procedure as P
    fn = getattr(M, name, None) or getattr(P, name)
    try:
        bound = _bind(fn, name, pos, kw)
    except Unsupported as e:
        rec.update(match=None, reason=str(e))
        log(rec)
        return
    if "root" in bound and isinstance(bound["root"], str):
        pass
    p_err = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            p_res = fn(**bound)
    except (RError, P.Stop) as e:
        p_res, p_err = None, str(e)
    except Exception as e:  # a Python bug, not an emulated R error
        rec.update(match=False, reason="python exception", py=traceback.format_exc()[-1500:], r=payload.get("error"))
        log(rec)
        return
    r_err = payload.get("error")
    if (r_err is None) != (p_err is None):
        rec.update(match=False, reason="error/no-error differs", r=r_err or to_plain(r_res), py=p_err or to_plain(p_res))
    elif r_err is not None:
        rec.update(match=True, reason="both raised an error", r=r_err, py=p_err)
    elif name in ("m_design", "m_execution", "m_ai", "m_finish", "m_change", "m_operations", "m_checkpoint_contract",
                  "m_operational_design", "m_validation", "m_source", "validate_stage_receipt"):
        ok, info = compare_checks(r_res, p_res)
        rec.update(match=ok, reason="checks equal" if ok else "checks differ", **info,
                   n_checks=len(norm_checks(r_res)), n_fail=sum(1 for c in norm_checks(r_res) if c[1] == "FAIL"))
    elif name == "m_inventory":
        a, b = to_plain(r_res), to_plain(p_res)
        ja, jb = json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str)
        if ja == jb:
            rec.update(match=True, reason="inventory equal (same order)")
        else:
            key = lambda x: json.dumps(x, sort_keys=True, default=str)
            same_set = isinstance(a, list) and isinstance(b, list) and sorted(map(key, a)) == sorted(map(key, b))
            rec.update(match=False, reason="inventory order differs (collation)" if same_set else "inventory differs", r=a, py=b)
    else:
        a, b = to_plain(r_res), to_plain(p_res)
        if name == "m_review_subjects":  # both are character vectors (NA = None); compare as lists
            a = a if isinstance(a, list) else [] if r_res is None else [a]
            b = b if isinstance(b, list) else [b]
        rec.update(match=json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str),
                   reason="value", r=a, py=b)
    log(rec)


# ------------------------------------------------------------------ whole-gate calls

def gate_py(kind, framework, out_path, args):
    os.environ["GATES_FRAMEWORK_ROOT"] = framework
    rec = {"kind": kind, "args": args}
    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            if kind == "workflow":
                from gates import workflow_gate as WG
                status, report, checks = WG.run(args[0], write=True)
                rec.update(status=status, report=WG.to_json(report) if report is not None else None,
                           checks=WG.to_json(checks) if checks is not None else None)
            else:
                import importlib
                from gates import procedure as P
                importlib.reload(P)
                status = P.main(args)
                rec.update(status=status)
    except Exception:
        rec.update(status="exception", exception=traceback.format_exc()[-3000:])
    rec.update(stdout=buf_out.getvalue(), stderr=buf_err.getvalue())
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, default=str)


def _json_or_none(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def gate_compare(py_path, r_path):
    with open(py_path, encoding="utf-8") as fh:
        py = json.load(fh)
    with open(r_path, encoding="utf-8") as fh:
        r = json.load(fh)
    kind = r["kind"]
    rec = {"kind": kind + "_gate", "name": (r["args"][0] if kind == "procedure" and r["args"] else "workflow_gate"),
           "args": r["args"]}
    if py.get("status") == "exception":
        rec.update(match=False, reason="python exception", py=py.get("exception"))
        log(rec)
        return
    r_status = int(r["status"] or 0)
    if kind == "workflow":
        r_report = None
        if r.get("report"):
            with open(r["report"], encoding="utf-8") as fh:
                r_report = json.load(fh)
        p_report = py.get("report")
        if r_report is None or p_report is None:
            ok = (r_report is None) == (p_report is None) and (r_status != 0) == (py["status"] != 0)
            rec.update(match=ok, reason="both halted without a report" if ok else "report present in one only",
                       r_status=r_status, py_status=py["status"], r_stderr=r["stderr"][-500:], py_stderr=py["stderr"][-500:])
        else:
            rv, pv = r_report.get("result"), p_report.get("result")
            ok_status = rv is not None and rv == pv and r_status == py["status"]
            ok_checks, info = compare_checks(r_report.get("checks"), p_report.get("checks"))
            rec.update(match=ok_status and ok_checks, reason=f"R {rv} (exit {r_status}) / Python {pv} (exit {py['status']})",
                       verdict=rv, n_checks=len(r_report.get("checks") or []), **info)
    else:
        r_out, p_out = _json_or_none(r["stdout"]), _json_or_none(py["stdout"])
        same_exit = (r_status != 0) == (py["status"] != 0)
        if r_out is None or p_out is None:
            ok = same_exit and (r_out is None) == (p_out is None)
            rec.update(match=ok, reason="both stopped with an error" if ok else "output differs",
                       r_status=r_status, py_status=py["status"], r_stderr=r["stderr"][-400:], py_stderr=py["stderr"][-400:],
                       r_stdout=r["stdout"][-400:], py_stdout=py["stdout"][-400:])
        else:
            rs = r_out.get("status", r_out.get("result")) if isinstance(r_out, dict) else None
            ps = p_out.get("status", p_out.get("result")) if isinstance(p_out, dict) else None
            ok = same_exit and rs == ps
            info = {}
            if isinstance(r_out, dict) and "checks" in r_out:
                ok_c, info = compare_checks(r_out.get("checks"), p_out.get("checks"))
                ok = ok and ok_c
            for key in ("workflow_gate", "blocked_by", "current_step", "completed_steps", "next_step"):
                if isinstance(r_out, dict) and key in r_out and key not in ("workflow_gate",):
                    if json.dumps(r_out.get(key), sort_keys=True) != json.dumps(p_out.get(key), sort_keys=True):
                        ok = False
                        info.setdefault("field_diffs", []).append({"field": key, "r": r_out.get(key), "py": p_out.get(key)})
            if isinstance(r_out, dict) and isinstance(r_out.get("workflow_gate"), dict):
                if (r_out["workflow_gate"] or {}).get("status") != ((p_out.get("workflow_gate") or {}).get("status")):
                    ok = False
                    info.setdefault("field_diffs", []).append({"field": "workflow_gate.status"})
            rec.update(match=ok, reason=f"R {rs} / Python {ps}", verdict=rs, **info)
    log(rec)


def main(argv):
    mode = argv[0]
    if mode == "fn":
        run_fn(argv[1])
    elif mode == "gate-py":
        gate_py(argv[1], argv[2], argv[3], argv[4:])
    elif mode == "gate-compare":
        gate_compare(argv[1], argv[2])
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception:
        log({"kind": "harness", "match": False, "reason": "harness exception", "py": traceback.format_exc()[-2000:]})
