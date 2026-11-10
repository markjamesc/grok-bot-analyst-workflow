"""Python port of methodology/contracts.R (methodology-v3 / acceptance-v1 / review coverage / H1).

Source: the R workflow repo, methodology/contracts.R at 8293a95 (main >= 28d2798).
Every function keeps the R name and returns the same check records ({"check", "result", "detail"}) in the
same order. Where R raises an error inside m_checks(), the port raises RError at the same point so the same
"Methodology well-formed contract" FAIL replaces the remaining checks. Parity: gates/parity_tests/.
"""
from __future__ import annotations

import calendar
import csv
import io
import math
import os
import re
import time

from .rsem import (AND, OR, NOT, D, DataFrame, RError, RVec, all_, any_, any_na, as_character, dollar, elements, elt,
                   identical, in_, is_character, is_list, is_logical, is_numeric, is_true, length, names, nzchar, r_if,
                   read_json_file, setequal, sha256_file, trimws, unlist, unlist_values, values, atomic_type, scalar_na,
                   str2num, _scalar_as_character)

ROLES7 = ["source", "fixtures", "reconciliation", "structural", "validation", "lineage", "methodology"]
_PLACEHOLDER = re.compile(r"^(TODO|TBD|REPLACE|PENDING|NOT_SET__|\{\{)", re.IGNORECASE)


# ------------------------------------------------------------------ R built-ins used by contracts.R

def _str1(x):
    """The string of a length-1 non-NA character value, else None."""
    if isinstance(x, str):
        return x
    if isinstance(x, RVec) and x.type == "chr" and len(x.v) == 1 and x.v[0] is not None:
        return x.v[0]
    return None


def _iter(xs):
    return elements(xs)


def _lgl_values(r):
    if isinstance(r, RVec):
        if r.type != "lgl":
            raise RError("values must be type 'logical'")
        return r.v
    if r is None:
        return []
    raise RError("values must be type 'logical'")


def vapply_lgl(xs, f):
    out = []
    for i, x in enumerate(_iter(xs)):
        r = f(x)
        if r is True or r is False:
            out.append(r)
            continue
        vs = _lgl_values(r)
        if len(vs) != 1:
            raise RError(f"values must be length 1,\n but FUN(X[[{i + 1}]]) result is length {len(vs)}")
        out.append(vs[0])
    return out


def vapply_chr(xs, f):
    out = []
    for i, x in enumerate(_iter(xs)):
        r = f(x)
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, RVec) and r.type == "chr" and len(r.v) == 1:
            out.append(r.v[0])
        elif length(r) != 1:
            raise RError(f"values must be length 1,\n but FUN(X[[{i + 1}]]) result is length {length(r)}")
        else:
            raise RError(f"values must be type 'character',\n but FUN(X[[{i + 1}]]) result is type '{atomic_type(r)}'")
    return out


def _filter_true(r):
    if r is True:
        return True
    if r is False or r is None:
        return False
    vs = values(r)
    return bool(vs) and vs[0] is True


def r_filter(f, xs):
    """Filter(f, x) as a python list of the kept elements."""
    return [x for x in _iter(xs) if _filter_true(f(x))]


def paste(*args, sep=" "):
    vecs = [as_character(a) for a in args]
    if all(len(v) == 0 for v in vecs):
        return []
    n = max(len(v) for v in vecs)
    vecs = [v if v else [""] for v in vecs]
    return [sep.join("NA" if v[i % len(v)] is None else v[i % len(v)] for v in vecs) for i in range(n)]


def paste1(*args, sep=" "):
    p = paste(*args, sep=sep)
    return p[0] if len(p) == 1 else RVec("chr", p)


def chr_vec(vals):
    if len(vals) == 1 and vals[0] is not None:
        return vals[0]
    return RVec("chr", vals)


def chr_or_null(xs):
    return None if xs is None else RVec("chr", list(xs))


def r_tolower(x):
    vs = as_character(x)
    out = [None if v is None else v.lower() for v in vs]
    return out[0] if len(out) == 1 and out[0] is not None else RVec("chr", out)


def anydup(xs):
    seen = set()
    for v in xs:
        k = ("NA",) if v is None else ("v", v)
        if k in seen:
            return True
        seen.add(k)
    return False


def unique(xs):
    out, seen = [], set()
    for v in xs:
        k = ("NA",) if v is None else ("v", v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def setdiff(x, y):
    ys = {("NA",) if v is None else ("v", v) for v in y}
    return [v for v in unique(x) if (("NA",) if v is None else ("v", v)) not in ys]


def strsplit_fixed(s, sep):
    if s == "":
        return []
    parts = s.split(sep)
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def as_list_chr(xs):
    return [v if v is not None else RVec("chr", [None]) for v in xs]


def rlapply(xs, f):
    return [f(x) for x in _iter(xs)]


def unlist_vec(x):
    v, t = unlist(x)
    return None if t is None else RVec(t, v)


def unique_vec(x):
    return None if x is None else RVec(x.type, unique(x.v))


def in1(value, table):
    r = in_(value, table)
    if len(r) == 1:
        return r[0]
    return RVec("lgl", r)


def lgl_vec(bools):
    return bools[0] if len(bools) == 1 else RVec("lgl", bools)


def values_or_empty(v):
    return [] if v is None else values(v)


def as_chr_list(vals):
    return [_scalar_as_character(v) if v is not None else None for v in vals]


def num1(x):
    return float(values(x)[0])


def _fpath(root, p):
    return f"{root}/{p}"


# ------------------------------------------------------------------ contracts.R core

def m_text(x):
    s = _str1(x)
    if s is None:
        return False
    t = trimws(s)
    return nzchar(t) and not _PLACEHOLDER.search(t)


def m_strings(x, empty=False):
    if x is None or not (is_list(x) or is_character(x)):
        return False
    if not length(x):
        return empty
    return all(m_text(e) for e in elements(x))


def m_enum(x, choices):
    s = _str1(x)
    return s is not None and s in choices


def m_number(x):
    if not is_numeric(x) or length(x) != 1:
        return False
    v = values(x)[0]
    return v is not None and math.isfinite(float(v))


def m_rows(x):
    return isinstance(x, list)


def m_read(path):
    try:
        return read_json_file(path)
    except RError:
        return None


def m_hash(path):
    return sha256_file(path)


_HEX64 = re.compile(r"^[a-fA-F0-9]{64}$")
_ABS = re.compile(r"^(/|[A-Za-z]:|\\)")


def m_ref_ok(ref, root):
    if not is_list(ref):
        return False
    path, sha = dollar(ref, "path"), dollar(ref, "sha256")
    if not m_text(path) or not m_text(sha):
        return False
    path, sha = _str1(path), _str1(sha)
    if not _HEX64.search(sha) or _ABS.search(path):
        return False
    if any(seg in ("", ".", "..") for seg in strsplit_fixed(path.replace("\\", "/"), "/")):
        return False
    f = _fpath(root, path)
    return (os.path.exists(f) and not os.path.isdir(f) and
            os.path.realpath(f).startswith(os.path.realpath(root) + "/") and sha.lower() == m_hash(f))


def m_refs(x):
    if not is_list(x):
        return []
    nm = names(x) or []
    if "path" in nm and "sha256" in nm:
        return [x]
    out = []
    for e in _iter(x):
        out.extend(m_refs(e))
    return out


def m_refs_ok(x, root, required=True):
    refs = m_refs(x)
    return (not required or len(refs) > 0) and all(m_ref_ok(r, root) for r in refs)


def m_equal_ids(actual, expected):
    if not (m_strings(actual, True) and m_strings(expected, True)):
        return False
    return not anydup(unlist_values(actual)) and setequal(actual, expected)


class Checks:
    def __init__(self, prefix="Methodology "):
        self.items = []
        self.prefix = prefix

    def add(self, name, ok, detail):
        if isinstance(name, RVec):
            nm = RVec("chr", [self.prefix + n for n in name.v])
        else:
            nm = self.prefix + name
        self.items.append({"check": nm, "result": "PASS" if ok is True else "FAIL", "detail": detail})


def m_checks(fun):
    c = Checks()
    try:
        fun(c.add)
    except RError as e:
        c.add("well-formed contract", False, str(e))
    return c.items


def _readd(add, checks):
    for x in checks:
        add(x["check"], x["result"] == "PASS", x["detail"])


def _all_text(obj, fields):
    return all(m_text(elt(obj, f)) for f in fields)


def m_design(s3, s2=None, s1=None, root=None):
    def body(add):
        _readd(add, m_checkpoint_contract(s3))
        _readd(add, m_operational_design(s3, root))
        m = dollar(s3, "methodology")
        add("version", identical(dollar(m, "version"), "methodology-v3"), "New runs require methodology-v3; old packs use their pinned referee")
        t = dollar(m, "analytical_target")
        fields = ["id", "decision_id", "question_id", "question_type", "target_population", "observed_population",
                  "analysis_unit", "decision_unit", "outcome", "time_origin", "horizon", "contrast", "aggregation",
                  "weighting", "quantity", "estimator", "decision_rule_ref", "validation_argument", "measurement_validity"]
        add("target complete", AND(is_list(t), lambda: _all_text(t, fields)), "Target, estimator and decision rule are separate")
        add("target decision rule reference", identical(dollar(t, "decision_rule_ref"), "stage3.decision_rules"), "Reference the existing decision rule authority")
        add("question type", m_enum(dollar(t, "question_type"), ["descriptive", "associational", "predictive", "causal", "decision"]), "Explicit question type")
        add("target population authority", AND(lambda: identical(dollar(t, "observed_population"), dollar(s3, "population")),
                                               lambda: identical(dollar(t, "decision_unit"), dollar(s3, "grain"))),
            "Existing population/grain remain authoritative; no conflicting duplicate")
        if s2 is not None:
            add("Framing link", AND(lambda: identical(dollar(t, "question_id"), dollar(s2, "question_id")),
                                    lambda: identical(dollar(t, "question_type"), dollar(s2, "question_type"))), "Target must address the framed question")
        if s1 is not None:
            add("decision link", identical(dollar(t, "decision_id"), dollar(s1, "decision_id")), "Target must address the Start decision")
        act = dollar(t, "allowed_claim_types")
        claim_types = RVec("chr", ["descriptive", "associational", "predictive", "causal", "recommendation"])
        add("claim ceiling", AND(m_strings(act), lambda: all_(in_(unlist_vec(act), claim_types))), "No numeric ordering of association/prediction/causation")
        trg = dollar(m, "triggers")
        causal = OR(identical(dollar(t, "question_type"), "causal"), lambda: in1("causal", unlist_vec(act)),
                    lambda: is_true(dollar(trg, "causal_policy")))
        predictive = OR(identical(dollar(t, "question_type"), "predictive"), lambda: in1("predictive", unlist_vec(act)),
                        lambda: identical(dollar(s3, "ml_mode"), "A"))
        if r_if(causal):
            add("causal identification", _all_text(t, ["treatment", "comparator", "identification_argument"]), "Identification is required; a forecast is not an intervention effect")
        exp_ = dollar(m, "exposure")
        add("prior exposure", AND(is_list(exp_), lambda: _all_text(exp_, ["data_seen", "results_seen", "test_set_access", "recorded_at_utc"])),
            "A new lock cannot erase prior outcome exposure")
        ps = dollar(m, "premises")

        def premise_ok(p):
            return AND(m_text(dollar(p, "id")),
                       lambda: m_enum(dollar(p, "kind"), ["definition", "source_assertion", "assumption", "method_choice", "preference", "limitation"]),
                       lambda: m_enum(dollar(p, "status"), ["proposed", "supported", "contradicted", "unresolved", "accepted_with_scope", "superseded"]),
                       lambda: m_enum(dollar(p, "testability"), ["direct", "diagnostic", "external", "not_identified", "not_applicable"]),
                       lambda: _all_text(p, ["statement", "basis", "consequence", "response"]))
        add("premise register", AND(m_rows(ps), lambda: length(ps) > 0, lambda: not anydup(vapply_chr(ps, lambda p: dollar(p, "id"))),
                                    lambda: all_(vapply_lgl(ps, premise_ok))),
            "Kind, support and testability are distinct; source agreement is not real-world truth")

        def trig_ok(f):
            v = elt(trg, f)
            return AND(is_logical(v), lambda: length(v) == 1, lambda: not scalar_na(v))
        triggers = ["missingness", "dependence", "multiplicity", "transportability", "causal_policy", "decision_outcome"]
        add("applicability screen", all_([trig_ok(f) for f in triggers]), "Explicit trigger assessment")
        required = {"measurement": True, "causal": causal, "predictive": predictive,
                    "missingness": is_true(dollar(trg, "missingness")), "dependence": is_true(dollar(trg, "dependence")),
                    "multiplicity": is_true(dollar(trg, "multiplicity")), "transportability": is_true(dollar(trg, "transportability")),
                    "decision_uncertainty": True}
        mods = dollar(m, "modules")
        for id_, req in required.items():
            mod = elt(mods, id_)
            add(f"module {id_}", AND(is_list(mod), lambda: identical(dollar(mod, "required"), req), lambda: m_text(dollar(mod, "rationale")),
                                     lambda: (m_text(dollar(mod, "plan")) if r_if(req) else identical(dollar(mod, "status"), "NOT_APPLICABLE"))),
                "Triggered modules need a project-specific plan; absent triggers need a reason")
        sp = dollar(m, "sensitivity")
        specs = dollar(sp, "specifications")
        add("sensitivity IDs unique", AND(m_rows(specs), lambda: not anydup(vapply_chr(specs, lambda x: dollar(x, "id")))), "No duplicated branch IDs")
        add("sensitivity screen", AND(is_logical(dollar(sp, "required")), lambda: length(dollar(sp, "required")) == 1, lambda: m_text(dollar(sp, "rationale")),
                                      lambda: m_text(dollar(sp, "instability_rule")), lambda: m_rows(specs)),
            "Bounded admissible alternatives; report failures and instability, never vote over specifications")

        def branch_ok(x):
            return AND(m_text(dollar(x, "id")), lambda: m_text(dollar(x, "justification")), lambda: m_text(dollar(x, "target_id")),
                       lambda: m_enum(dollar(x, "relation"), ["same_target", "supplementary_target"]),
                       lambda: (identical(dollar(x, "target_id"), dollar(t, "id")) if identical(dollar(x, "relation"), "same_target")
                                else not identical(dollar(x, "target_id"), dollar(t, "id"))))
        add("sensitivity branches", AND(OR(not is_true(dollar(sp, "required")), lambda: length(specs) > 0), lambda: all_(vapply_lgl(specs, branch_ok))),
            "Different targets are supplementary, not robustness votes")
        cp = dollar(m, "checkpoints")

        def cp_ok(x):
            return AND(m_text(dollar(x, "id")), lambda: m_strings(dollar(x, "keys")), lambda: m_strings(dollar(x, "exact_fields"), True),
                       lambda: m_strings(dollar(x, "numeric_fields"), True), lambda: m_number(dollar(x, "absolute_tolerance")),
                       lambda: num1(dollar(x, "absolute_tolerance")) >= 0, lambda: m_number(dollar(x, "relative_tolerance")),
                       lambda: num1(dollar(x, "relative_tolerance")) >= 0, lambda: m_text(dollar(x, "rationale")))
        add("checkpoint plan", AND(m_rows(cp), lambda: length(cp) > 0, lambda: not anydup(vapply_chr(cp, lambda x: dollar(x, "id"))),
                                   lambda: all_(vapply_lgl(cp, cp_ok))),
            "Semantic keyed states, not identical algorithms; exact identities and decisions")
        exact_covered = unique_vec(unlist_vec([[dollar(x, "keys"), dollar(x, "exact_fields")] for x in _iter(cp)]))
        numeric_covered = unique_vec(unlist_vec([dollar(x, "numeric_fields") for x in _iter(cp)]))
        both = unlist_vec([exact_covered, numeric_covered])
        edf = dollar(m, "exact_decision_fields")
        add("critical fields covered", AND(all_(in_(unlist_vec(dollar(s3, "reconciliation_critical_fields")), both)),
                                           lambda: m_strings(edf), lambda: all_(in_(unlist_vec(edf), exact_covered)),
                                           lambda: not any_(in_(unlist_vec(edf), numeric_covered))),
            "Decision/identity fields exact; other critical quantities use locked tolerances")
        cc = dollar(m, "checkpoint_coverage")
        add("checkpoint coverage", AND(m_strings(cc), lambda: all_(in_(RVec("chr", ["population", "exclusions", "components", "results"]), unlist_vec(cc)))),
            "Document where membership, exclusions, numerators/denominators and results are compared")
        add("numeric boundary policy", _all_text(dollar(m, "numerics"), ["boundary_rule", "nonfinite_rule", "stochastic_rule"]),
            "Retains C39; does not adopt rejected C46 or permit post hoc tolerance widening")
        mt = dollar(m, "metamorphic")
        add("metamorphic IDs unique", AND(m_rows(mt), lambda: not anydup(vapply_chr(mt, lambda x: dollar(x, "id")))), "No duplicated relation IDs")

        def mr_ok(x):
            ap = dollar(x, "applicable")
            return AND(m_text(dollar(x, "id")), lambda: is_logical(ap), lambda: length(ap) == 1, lambda: m_text(dollar(x, "preconditions")),
                       lambda: m_text(dollar(x, "rationale")),
                       lambda: OR(not is_true(ap), lambda: AND(m_text(dollar(x, "transformation")), lambda: m_text(dollar(x, "expected_relation")))))
        add("metamorphic applicability", AND(m_rows(mt), lambda: length(mt) > 0, lambda: all_(vapply_lgl(mt, mr_ok))),
            "Assess row order and unused fields; only valid relations must run")
        sr = dollar(m, "structural_review")
        add("structural disposition", AND(m_enum(dollar(sr, "policy"), ["required", "conditional"]), lambda: m_text(dollar(sr, "rationale")),
                                          lambda: m_strings(dollar(sr, "fixture_covered_rule_ids"), True)),
            "C30 relaxation requires coverage or review for uncovered rules")
        add("rule coverage", AND(m_strings(dollar(m, "judged_rule_ids")),
                                 lambda: all_(in_(unlist_vec(dollar(sr, "fixture_covered_rule_ids")), unlist_vec(dollar(m, "judged_rule_ids"))))),
            "Coverage names actual locked rules")
        add("dominance plan", _all_text(dollar(m, "dominance"), ["unit", "metric", "thresholds", "rationale", "flag_consequence"]),
            "Project-specific; 1000/30/one-third are not universal defaults; never auto-exclude")
        of = dollar(m, "output_fields")
        add("output-field completeness", AND(m_rows(of), lambda: m_equal_ids(rlapply(of, lambda x: dollar(x, "field")), dollar(s3, "required_outputs")),
                                             lambda: all_(vapply_lgl(of, lambda x: m_text(dollar(x, "outcome_semantics"))))),
            "C53: every required output defines all outcomes including null/empty cases")
        add("replay output plan", m_strings(dollar(m, "replay_outputs")), "Lock all deterministic critical output file paths before running")
        rd = dollar(m, "receipt_dependencies")
        add("dependency coverage plan", AND(is_list(rd), lambda: all_(in_(RVec("chr", ROLES7), chr_or_null(names(rd)))), lambda: all_(vapply_lgl(rd, m_strings))),
            "Lock project-relative dependencies per receipt, including inputs, code/config and outputs")
        if is_true(dollar(trg, "decision_outcome")):
            add("outcome contract", _all_text(dollar(m, "outcome_contract"), ["action", "alternative", "window", "metric", "counterfactual_design",
                                                                              "minimum_worthwhile_gain", "guardrails", "owner", "followup_run_id"]),
                "Comparison fixed before outcomes; profit requires costs; follow-up does not reopen original question")
    return m_checks(body)


# Compare named semantic tables, preserving string identifiers (including leading zeros).
def _colvals(d, f):
    c = d.cols[f]
    return list(c.v) if isinstance(c, RVec) else list(c)


def _colchr(d, f):
    """as.character(d[[f]]) element-wise (NA -> None)."""
    c = d.cols[f]
    if isinstance(c, RVec):
        return [None if v is None else _scalar_as_chr(v) for v in c.v]
    raise RError("list column")  # as.character on a list column deparses; not produced by read.csv


def _scalar_as_chr(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return num2str(v)
    return str(v)


def _num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return str2num(v)


def _radix_key(v):
    if v is None:
        return (1, 0)
    if isinstance(v, (bool, int, float)):
        return (0, float(v))
    return (0, v.encode("utf-8", "surrogateescape"))


def m_compare(a, b, plan):
    keys = as_chr_list(unlist_values(dollar(plan, "keys")))
    exact_f = as_chr_list(unlist_values(dollar(plan, "exact_fields")))
    num_f = as_chr_list(unlist_values(dollar(plan, "numeric_fields")))
    fields = unique(keys + exact_f + num_f)
    if not isinstance(a, DataFrame) or not isinstance(b, DataFrame):
        return False
    if a.dup_names or b.dup_names or not all(f in a.cols for f in fields) or not all(f in b.cols for f in fields):
        return False

    def canonical(d):
        kv = [_colvals(d, k) for k in keys]
        if any(v is None or (isinstance(v, float) and v != v) for col in kv for v in col):
            return None
        rows = [tuple(col[i] for col in kv) for i in range(d.nrow)]
        if anydup(rows):
            return None
        if any(any(not nzchar(trimws(x)) for x in _colchr(d, k)) for k in keys):
            return None
        idx = sorted(range(d.nrow), key=lambda i: tuple(_radix_key(v) for v in rows[i]))
        return idx
    ia, ib = canonical(a), canonical(b)
    if ia is None or ib is None or a.nrow != b.nrow:
        return False

    def col(d, idx, f, chr_=True):
        v = _colchr(d, f) if chr_ else _colvals(d, f)
        return [v[i] for i in idx]
    for f in unique(keys + exact_f):
        if col(a, ia, f) != col(b, ib, f):
            return False
    miss = dollar(plan, "numeric_missingness")
    for f in num_f:
        x = [_num(v) for v in col(a, ia, f, False)]
        y = [_num(v) for v in col(b, ib, f, False)]
        rule = elt(miss, f)
        keep = [True] * len(x)
        if rule is not None:
            if not _filter_true(m_missing_rule(rule, plan)) or _str1(dollar(rule, "flag_field")) not in a.cols:
                return False
            ff = _str1(dollar(rule, "flag_field"))
            fa, fb = col(a, ia, ff), col(b, ib, ff)
            mv = values_or_empty(m_missing_values(rule))
            pv = _str1(dollar(rule, "present_value"))
            if any(v is None for v in fa) or fa != fb or not all(v in mv or v == pv for v in fa):
                return False
            missing = [v in mv for v in fa]
            tok = _str1(dollar(rule, "missing_token"))
            ca, cb = col(a, ia, f), col(b, ib, f)
            if any(ca[i] is None or cb[i] is None for i in range(len(x)) if missing[i]):
                return False
            if not all(ca[i] == tok and cb[i] == tok for i in range(len(x)) if missing[i]):
                return False
            keep = [not z for z in missing]
        xs = [x[i] for i in range(len(x)) if keep[i]]
        ys = [y[i] for i in range(len(y)) if keep[i]]
        if not all(v is not None and math.isfinite(v) for v in xs) or not all(v is not None and math.isfinite(v) for v in ys):
            return False
        at, rt = dollar(plan, "absolute_tolerance"), dollar(plan, "relative_tolerance")
        if not xs or at is None or rt is None:
            continue  # R: NULL tolerance gives a zero-length comparison, and all() of it is TRUE
        if atomic_type(at) not in ("lgl", "int", "dbl") or atomic_type(rt) not in ("lgl", "int", "dbl"):
            raise RError("non-numeric argument to binary operator")
        if length(at) != 1 or length(rt) != 1 or values(at)[0] is None or values(rt)[0] is None:
            return False
        at, rt = num1(at), num1(rt)
        if not all(abs(p - q) <= at + rt * max(abs(p), abs(q)) for p, q in zip(xs, ys)):
            return False
    return True


def m_csv(ref, root):
    """read.csv(file, colClasses = 'character', check.names = FALSE, na.strings = character())."""
    path = _fpath(root, _str1(dollar(ref, "path")))
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        raise RError(str(e))
    text = raw.decode("utf-8", "surrogateescape")
    rows = [r for r in csv.reader(io.StringIO(text, newline="")) if r and not (len(r) == 1 and r[0] == "")]
    if not rows:
        raise RError("no lines available in input")
    header, data = rows[0], rows[1:]
    ncol = len(header)
    cols = [[] for _ in range(ncol)]
    for r in data:
        if len(r) > ncol:
            raise RError("more columns than column names")
        for j in range(ncol):
            cols[j].append(r[j] if j < len(r) else "")
    df = DataFrame({}, len(data))
    for j, h in enumerate(header):
        if h in df.cols:
            df.dup_names = True
        else:
            df.cols[h] = RVec("chr", cols[j])
    return df


def m_execution(s3, s4, root):
    def body(add):
        _readd(add, m_source(s3, s4, root))
        m = dollar(s3, "methodology")
        add("design gate", all_([x["result"] == "PASS" for x in m_design(s3, root=root)]), "Design contract must pass even when Workflow Gate is called directly")
        er = dollar(s4, "evidence_receipts")
        roles = names(er)
        rd = dollar(m, "receipt_dependencies")
        add("receipt dependency coverage", all_(in_(chr_or_null(names(rd)), chr_or_null(roles))), "All locked receipt roles are present")
        for role in (roles or []):
            ref = elt(er, role)
            ok = m_ref_ok(ref, root)
            r = m_read(_fpath(root, _str1(dollar(ref, "path")))) if ok else None
            peers = unlist_values([dollar(er[k], "path") for k in er if k not in (role,)])

            def dep_ok(r=r, role=role, ok=ok, peers=peers):
                return AND(ok, lambda: identical(dollar(r, "design_sha256"), m_hash(_fpath(root, "artifacts/stage3_locked_design.json"))),
                           lambda: m_refs_ok(dollar(r, "dependencies"), root),
                           lambda: m_equal_ids(rlapply(dollar(r, "dependencies"), lambda d: dollar(d, "path")),
                                               as_list_chr(setdiff(unlist_values(elt(rd, role)), peers))))
            add(f"dependencies {role}", dep_ok(), "PASS binds exact design and declared source/code/config/output dependencies; no other role's receipt")
        ref = dollar(er, "methodology")
        r = m_read(_fpath(root, _str1(dollar(ref, "path")))) if m_ref_ok(ref, root) else None
        _readd(add, m_validation(s3, r, root))
        add("methodology evidence", AND(is_list(r), lambda: identical(dollar(r, "status"), "PASS"),
                                        lambda: identical(dollar(r, "target_id"), D(m, "analytical_target", "id"))),
            "Actual output identities and target must match")
        cps = dollar(r, "checkpoints")
        mcp = dollar(m, "checkpoints")
        add("checkpoint IDs", AND(m_rows(cps), lambda: m_equal_ids(rlapply(cps, lambda x: dollar(x, "id")), rlapply(mcp, lambda x: dollar(x, "id")))),
            "No missing or duplicate checkpoints")
        for p in _iter(mcp):
            matches = r_filter(lambda x: identical(dollar(x, "id"), dollar(p, "id")), cps)
            x = matches[0] if len(matches) == 1 else None
            ok = AND(m_ref_ok(dollar(x, "a"), root), lambda: m_ref_ok(dollar(x, "b"), root))
            add(paste1("checkpoint", dollar(p, "id")),
                AND(ok, lambda: m_compare(m_csv(dollar(x, "a"), root), m_csv(dollar(x, "b"), root), p)),
                "Recomputed key membership and exact/numeric field comparisons")
        tests = dollar(r, "metamorphic")
        app = r_filter(lambda x: is_true(dollar(x, "applicable")), dollar(m, "metamorphic"))
        expected = unlist_values([RVec("chr", paste(dollar(x, "id"), RVec("chr", ["R-A", "R-B"]), sep=":")) for x in app])
        actual = rlapply(tests, lambda x: chr_vec(paste(dollar(x, "id"), dollar(x, "path_id"), sep=":")))
        add("metamorphic coverage", AND(m_rows(tests), lambda: m_equal_ids(actual, as_list_chr(expected)),
                                        lambda: all_(vapply_lgl(tests, lambda x: AND(identical(dollar(x, "result"), "PASS"), lambda: m_ref_ok(dollar(x, "report"), root))))),
            "Both implementations run every applicable relation; referenced reports retained")
        specs = dollar(r, "sensitivity")
        add("sensitivity coverage", AND(m_rows(specs), lambda: m_equal_ids(rlapply(specs, lambda x: dollar(x, "id")), rlapply(D(m, "sensitivity", "specifications"), lambda x: dollar(x, "id"))),
                                        lambda: all_(vapply_lgl(specs, lambda x: AND(m_enum(dollar(x, "status"), ["evaluated", "failed"]), lambda: m_ref_ok(dollar(x, "report"), root),
                                                                                    lambda: m_text(dollar(x, "interpretation")))))),
            "Keep failed branches; instability restricts claims rather than being hidden")
        mods = dollar(m, "modules")
        rmods = dollar(r, "modules")

        def mod_ok(id_):
            p = elt(mods, id_)
            x = elt(rmods, id_)
            if is_true(dollar(p, "required")):
                return AND(m_enum(dollar(x, "disposition"), ["adequate", "scope_restricted", "insufficient"]),
                           lambda: m_text(dollar(x, "interpretation")), lambda: m_ref_ok(dollar(x, "report"), root))
            return identical(dollar(x, "disposition"), "NOT_APPLICABLE")
        add("module coverage", AND(is_list(rmods), lambda: all_([mod_ok(i) for i in (names(mods) or [])])),
            "Scientific inadequacy may narrow inference; computational failure never becomes a PASS by choosing hold")
        fx = dollar(r, "fixtures")
        add("fixture depth", AND(identical(dollar(fx, "production_reader_a"), "PASS"), lambda: identical(dollar(fx, "production_reader_b"), "PASS"),
                                 lambda: identical(dollar(fx, "poison_probe_a"), "PASS"), lambda: identical(dollar(fx, "poison_probe_b"), "PASS"),
                                 lambda: m_ref_ok(dollar(fx, "report"), root)),
            "C41: reader roundtrip plus tests that reject a poison judge")
        sm = dollar(r, "smoke")
        add("smoke runs", AND(identical(dollar(sm, "status"), "PASS"), lambda: is_true(dollar(sm, "non_reporting")), lambda: m_ref_ok(dollar(sm, "report"), root)),
            "C51 run provenance only; smoke outputs cannot become analytical evidence")
        dm = dollar(r, "dominance")
        add("dominance evidence", AND(m_enum(dollar(dm, "status"), ["NO_FLAG", "FLAG", "NOT_APPLICABLE"]), lambda: m_text(dollar(dm, "disposition")),
                                      lambda: m_ref_ok(dollar(dm, "report"), root)),
            "Flag disclosure implements locked consequences; no silent row dropping")
        env = dollar(r, "reproducibility")
        envf = ["r_version", "os", "locale", "timezone", "encoding", "rng", "seeds", "sql_client", "sql_mode", "threads", "workflow_commit",
                "project_commit", "working_tree", "replay_command", "retention"]
        add("environment manifest", AND(_all_text(env, envf), lambda: m_ref_ok(dollar(env, "package_lock"), root), lambda: m_ref_ok(dollar(env, "session_info"), root)),
            "Use explicit unavailable/not-applicable with reason; never invent hosted details")
        replay = dollar(r, "replay")
        outs = dollar(replay, "outputs")
        add("replay output coverage", m_equal_ids(rlapply(outs, lambda x: D(x, "original", "path")), dollar(m, "replay_outputs")),
            "Replay every locked critical output, not a convenient subset")
        add("clean replay", AND(is_true(dollar(replay, "clean_session")), lambda: identical(dollar(replay, "exit_status"), 0),
                                lambda: identical(dollar(replay, "status"), "PASS"), lambda: m_ref_ok(dollar(replay, "report"), root),
                                lambda: m_rows(outs), lambda: length(outs) > 0,
                                lambda: all_(vapply_lgl(outs, lambda x: AND(m_ref_ok(dollar(x, "original"), root), lambda: m_ref_ok(dollar(x, "replayed"), root),
                                                                           lambda: identical(D(x, "original", "sha256"), D(x, "replayed", "sha256")))))),
            "Replay deterministic published outputs; stochastic inference uses locked persisted fit/splits; no AI regeneration required")
        res = dollar(r, "results")
        add("result inventory", AND(m_rows(res), lambda: length(res) > 0, lambda: not anydup(vapply_chr(res, lambda x: dollar(x, "id"))),
                                    lambda: all_(vapply_lgl(res, lambda x: AND(m_text(dollar(x, "id")), lambda: m_text(dollar(x, "locator")),
                                                                              lambda: identical(dollar(x, "target_id"), D(m, "analytical_target", "id")),
                                                                              lambda: m_ref_ok(dollar(x, "artifact"), root))))),
            "Authoritative result IDs and artifact locations for Finish")
        ch = dollar(r, "changes")
        add("execution change log", AND(m_rows(ch), lambda: all_(vapply_lgl(ch, lambda x: all_([c["result"] == "PASS" for c in m_change(x)])))),
            "Corrections, amendments and exploration retain exposure and dependency impact; empty list only when no changes")
        add("all evidence references current", m_refs_ok(r, root), "Includes nested checkpoint, replay, sensitivity and test report bytes")
    return m_checks(body)


def _r_as_list(x):
    """as.list(x)."""
    if x is None:
        return []
    if isinstance(x, RVec):
        return list(x.v)
    if isinstance(x, dict):
        return list(x.values())
    if isinstance(x, list):
        return list(x)
    return [x]


def m_ai(records, roles, root, stage):
    def body(add):
        add(f"{stage} AI role coverage", AND(m_rows(records), lambda: m_equal_ids(rlapply(records, lambda x: dollar(x, "role")), _r_as_list(roles))),
            "Observable provenance, not a guarantee of independent errors")
        fields = ["provider", "model", "session", "settings", "seeds", "context_disclosure", "first_pass_frozen_at", "peer_access", "contamination"]
        for x in _iter(records):
            add(paste1(stage, "AI provenance", dollar(x, "role")),
                AND(_all_text(x, fields), lambda: m_ref_ok(dollar(x, "input"), root), lambda: m_ref_ok(dollar(x, "output"), root)),
                "Archive visible inputs/outputs; unavailable metadata explicitly disclosed; no hidden reasoning requested")
            if stage == "execution":
                add(paste1("build barrier", dollar(x, "role")), identical(dollar(x, "peer_access"), "none_before_freeze"), "R-A/R-B build independence retained")
            if stage == "design":
                add(paste1("no coordinator draft", dollar(x, "role")), identical(dollar(x, "coordinator_draft_seen"), False), "C02 retained; peer exposure allowed under C01 and disclosed")
    return m_checks(body)


def m_words(text, lexicon):
    joined = " ".join(v if v is not None else "NA" for v in as_character(text)).replace("_", " ").lower()
    words = re.split(r"[\W_]+", joined)
    lex = [v.lower() for v in as_chr_list(unlist_values(lexicon)) if v is not None]
    return any(w in words for w in lex)


def m_finish(s3, s4, s5, root):
    def body(add):
        ref = D(s4, "evidence_receipts", "methodology")
        evidence = m_read(_fpath(root, _str1(dollar(ref, "path")))) if m_ref_ok(ref, root) else None
        claims = dollar(s5, "claim_ledger")
        add("claim coverage", AND(m_rows(claims), lambda: length(claims) > 0,
                                  lambda: m_equal_ids(rlapply(claims, lambda c: dollar(c, "id")), dollar(s5, "substantive_claim_ids"))),
            "Reviewer-declared inventory must cover every substantive deliverable claim")
        meth = dollar(s3, "methodology")
        target = dollar(meth, "analytical_target")
        fields = ["wording", "warrant", "contrary_evidence", "defeater", "uncertainty", "scope", "sensitivity", "reviewer", "disposition"]
        for c in _iter(claims):
            add(paste1("claim", dollar(c, "id")),
                AND(identical(dollar(c, "target_id"), dollar(target, "id")),
                    lambda: m_enum(dollar(c, "type"), [v for v in as_chr_list(unlist_values(dollar(target, "allowed_claim_types"))) if v is not None]),
                    lambda: _all_text(c, fields),
                    lambda: m_strings(dollar(c, "result_ids")),
                    lambda: all_(in_(unlist_vec(dollar(c, "result_ids")), chr_or_null(vapply_chr(dollar(evidence, "results"), lambda x: dollar(x, "id"))))),
                    lambda: m_strings(dollar(c, "premise_ids"), True),
                    lambda: all_(in_(unlist_vec(dollar(c, "premise_ids")), chr_or_null(vapply_chr(dollar(meth, "premises"), lambda x: dollar(x, "id"))))),
                    lambda: identical(dollar(c, "numerical_audit"), "PASS"), lambda: identical(dollar(c, "inference_review"), "PASS"),
                    lambda: identical(dollar(c, "unresolved_objections"), 0),
                    lambda: m_ref_ok(dollar(c, "review_evidence"), root), lambda: m_ref_ok(dollar(c, "deliverable"), root),
                    lambda: in1(D(c, "deliverable", "path"), unlist_vec(dollar(s5, "deliverables")))),
                "Numbers and inferential warrants reviewed separately; gate does not establish truth")
            if OR(identical(dollar(c, "type"), "recommendation"), lambda: m_words(dollar(c, "wording"), D(meth, "operational", "action_lexicon"))):
                add(paste1("action values", dollar(c, "id")),
                    AND(m_text(dollar(c, "owner_tradeoff")), lambda: m_text(dollar(c, "action")), lambda: m_text(dollar(c, "evidence_tag")),
                        lambda: m_text(dollar(c, "tag_assigned_by"))),
                    "C37 tag assigned by coordinator from reviewed claims; action lexicon locked in Design")
        if any_(vapply_lgl(claims, lambda c: m_words(dollar(c, "wording"), D(meth, "operational", "finality_lexicon")))):
            add("finality review", m_ref_ok(dollar(s5, "monitoring_next_question_review"), root), "Finality wording requires explicit monitoring/next-question interpretation")
        ccr = dollar(s5, "claim_coverage_review")
        add("claim inventory audit", AND(identical(dollar(ccr, "status"), "PASS"), lambda: m_ref_ok(dollar(ccr, "report"), root)), "No automatic natural-language completeness claim")
        assurance = dollar(s5, "assurance")
        if identical(dollar(assurance, "outcome_evaluation"), "evaluated"):
            add("evaluated outcome evidence", m_ref_ok(D(s5, "outcome_followup", "evaluation_report"), root), "Evaluated outcomes require a linked report, not a status alone")
        rev = dollar(s5, "revision")
        add("revision disposition", AND(m_enum(dollar(rev, "status"), ["UNCHANGED", "PASS"]), lambda: identical(dollar(rev, "unresolved_flags"), 0),
                                        lambda: m_ref_ok(dollar(rev, "report"), root)),
            "C48/C50 one consolidated revision plus mechanical verification; unresolved FLAG blocks Finish")

        def inad(x):
            r = in_(dollar(x, "disposition"), RVec("chr", ["scope_restricted", "insufficient"]))
            return r[0] if len(r) == 1 else RVec("lgl", r)
        inadequate = any_(vapply_lgl(dollar(evidence, "modules"), inad))
        add("inference reflects module limitations", OR(NOT(inadequate), lambda: lgl_vec(in_(dollar(assurance, "inference"), RVec("chr", ["scope_restricted", "insufficient"])))),
            "Cannot upgrade an inadequate method module to blanket adequacy in the certificate")
        add("separate assurance dimensions", AND(identical(dollar(assurance, "computation"), "verified"),
                                                 lambda: m_enum(dollar(assurance, "inference"), ["adequate", "scope_restricted", "insufficient"]),
                                                 lambda: m_enum(dollar(assurance, "decision"), ["act", "pilot", "hold", "insufficient_evidence", "no_action_required"]),
                                                 lambda: m_enum(dollar(assurance, "outcome_evaluation"), ["not_applicable", "pending", "evaluated"])),
            "Procedure PASS does not imply profitable action or causal validity")
        if is_true(D(meth, "triggers", "decision_outcome")):
            locked = dollar(meth, "outcome_contract")
            handoff = dollar(s5, "outcome_followup")
            contract_ok = m_ref_ok(dollar(handoff, "contract"), root)
            saved = m_read(_fpath(root, _str1(D(handoff, "contract", "path")))) if contract_ok else None
            add("outcome handoff", AND(identical(dollar(handoff, "run_id"), dollar(locked, "followup_run_id")),
                                       lambda: identical(dollar(handoff, "owner"), dollar(locked, "owner")), contract_ok, lambda: is_list(saved),
                                       lambda: setequal(chr_or_null(names(saved)), chr_or_null(names(locked))),
                                       lambda: all_([identical(elt(saved, k), elt(locked, k)) for k in (names(locked) or [])])),
                "Handoff JSON preserves the locked comparison and owner; changes require amendment")
            add("required outcome status", m_enum(dollar(assurance, "outcome_evaluation"), ["pending", "evaluated"]),
                "Required follow-up cannot be relabeled not applicable; pending is an honest unknown outcome")
    return m_checks(body)


def m_change(change):
    def body(add):
        add("change classification", m_enum(dollar(change, "change_class"), ["implementation_correction", "design_amendment", "exploratory", "presentation"]),
            "Record what changed, not whether the result is convenient")
        add("exposure disclosure", AND(m_text(dollar(change, "results_seen")), lambda: m_text(dollar(change, "data_seen")), lambda: m_text(dollar(change, "reason"))),
            "Post-result locks remain post-result")
        add("dependency invalidation", AND(m_strings(dollar(change, "affected_artifacts")), lambda: m_strings(dollar(change, "rerun_steps")),
                                           lambda: m_text(dollar(change, "target_effect"))),
            "Invalidate and rerun affected dependency closure")
        if identical(dollar(change, "change_class"), "implementation_correction"):
            add("unchanged design", AND(identical(dollar(change, "target_effect"), "unchanged"), lambda: m_text(dollar(change, "locked_clause"))),
                "A correction implements the same locked clause")
        if identical(dollar(change, "change_class"), "exploratory"):
            add("exploration separate", identical(dollar(change, "confirmatory"), False), "Exploration cannot silently amend confirmatory evidence")
    return m_checks(body)


_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


def m_time(x):
    if not m_text(x) or not _TIME.search(_str1(x)):
        return None
    s = _str1(x)
    y, mo, d, hh, mi, ss = int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19])
    if not (1 <= mo <= 12 and 1 <= d <= 31 and hh <= 24 and mi <= 59 and ss <= 61):
        return None
    return float(calendar.timegm((y, mo, 1, 0, 0, 0)) + (d - 1) * 86400 + hh * 3600 + mi * 60 + ss)


def m_operational_design(s3, root):
    def body(add):
        o = D(s3, "methodology", "operational")
        sc = dollar(o, "source_contract")
        add("source applicability locked", AND(m_enum(dollar(sc, "kind"), ["sql", "file"]), lambda: m_text(dollar(sc, "rationale"))),
            "File-only inputs do not imply a SQL gate PASS")
        add("operational version", identical(dollar(o, "version"), "acceptance-v1"), "Prospective contracts require acceptance-v1")
        add("language rules", AND(m_strings(dollar(o, "action_lexicon")), lambda: m_strings(dollar(o, "finality_lexicon")),
                                  lambda: m_text(dollar(o, "negation_rule")), lambda: m_text(dollar(o, "evidence_tag_rule"))),
            "Lock lexical triggers; contextual review remains human/AI work")
        add("frozen fixture oracle", AND(m_ref_ok(dollar(o, "fixture_inputs"), root), lambda: m_ref_ok(dollar(o, "fixture_expected"), root),
                                         lambda: m_text(dollar(o, "oracle_basis")), lambda: m_text(dollar(o, "oracle_reviewer"))),
            "Input and independently justified expected answers frozen in Design")
        orules = dollar(o, "output_rules")
        add("output rules", AND(m_rows(orules), lambda: m_equal_ids(rlapply(orules, lambda x: dollar(x, "field")), dollar(s3, "required_outputs")),
                                lambda: all_(vapply_lgl(orules, lambda x: AND(m_enum(dollar(x, "kind"), ["literal", "enum", "computed"]), lambda: m_text(dollar(x, "rule")))))),
            "Every output defines literal, enum or computed semantics")
        pr = dollar(o, "packet_requirements")
        add("packet contract", AND(m_strings(pr), lambda: all_(in_(RVec("chr", ["output_rules", "checkpoint_output_rules", "checkpoints", "receipt_dependencies", "accepted_code"]), unlist_vec(pr)))),
            "Execution packets carry authoritative sections, not summaries")
        v = dollar(o, "validation_components")

        def comp_path_ok(p):
            s = as_chr_list([p])[0]
            if s is None:
                return False
            return (not re.search(r"^(/|[A-Za-z]:)", s)) and not any(seg in ("", ".", "..") for seg in strsplit_fixed(s, "/"))
        add("test component coverage", AND(is_list(v), lambda: setequal(chr_or_null(names(v)), RVec("chr", ["R-A", "R-B", "harness", "configuration", "input"])),
                                           lambda: all_(vapply_lgl(v, m_strings)), lambda: all_([comp_path_ok(p) for p in unlist_values(v)])),
            "Lock project-relative component paths, bind hashes at execution")
        for x in _iter(D(s3, "methodology", "metamorphic")):
            if is_true(dollar(x, "applicable")):
                add(paste1("MR discrimination", dollar(x, "id")),
                    AND(m_enum(dollar(x, "coverage_type"), ["nonconstant", "boundary", "negative_control"]), lambda: m_text(dollar(x, "detectable_defect"))),
                    "Do not certify effectiveness from an empty or constant output alone")
    return m_checks(body)


def m_validation(s3, receipt, root):
    def body(add):
        v = dollar(receipt, "test_versions")
        locked = D(s3, "methodology", "operational", "validation_components")
        comps = dollar(v, "components")

        def comp_ok(k):
            ck = elt(comps, k)
            return AND(m_rows(ck), lambda: m_refs_ok(ck, root), lambda: m_equal_ids(rlapply(ck, lambda x: dollar(x, "path")), elt(locked, k)))
        add("validation component identities", AND(is_list(comps), lambda: setequal(chr_or_null(names(comps)), chr_or_null(names(locked))),
                                                   lambda: all_([comp_ok(k) for k in (names(locked) or [])])),
            "Every test binds current R-A/R-B, harness, configuration and input bytes")
        app = r_filter(lambda x: is_true(dollar(x, "applicable")), D(s3, "methodology", "metamorphic"))
        expected = ["fixtures:R-A", "fixtures:R-B", "replay", "reconciliation"] + unlist_values(
            [RVec("chr", paste("metamorphic", dollar(x, "id"), RVec("chr", ["R-A", "R-B"]), sep=":")) for x in app])
        tests = dollar(v, "tests")
        add("versioned test coverage", AND(m_rows(tests), lambda: m_equal_ids(rlapply(tests, lambda x: dollar(x, "id")), as_list_chr(expected))),
            "No missing or duplicate versioned tests")
        for x in _iter(tests):
            rep = dollar(x, "report")
            r = m_read(_fpath(root, _str1(dollar(rep, "path")))) if m_ref_ok(rep, root) else None
            add(paste1("versioned result", dollar(x, "id")),
                AND(identical(dollar(x, "result"), "PASS"), lambda: identical(dollar(x, "components"), comps),
                    lambda: identical(dollar(r, "id"), dollar(x, "id")), lambda: identical(dollar(r, "result"), "PASS"),
                    lambda: identical(dollar(r, "components"), dollar(x, "components")),
                    lambda: identical(dollar(r, "recorded_at_utc"), dollar(x, "recorded_at_utc")),
                    lambda: m_time(dollar(x, "recorded_at_utc")) is not None,
                    lambda: m_time(dollar(x, "recorded_at_utc")) <= time.time() + 2),
                "Actual report embeds tested versions; refreshing a receipt wrapper is insufficient")
        tri = dollar(receipt, "triage")

        def tri_ok(x):
            return AND(m_text(dollar(x, "id")), lambda: m_text(dollar(x, "disposition")),
                       lambda: OR(identical(dollar(x, "status"), "resolved"),
                                  lambda: AND(identical(dollar(x, "status"), "accepted_limitation"), lambda: not identical(dollar(x, "severity"), "blocking"),
                                              lambda: m_ref_ok(dollar(x, "owner_approval"), root))),
                       lambda: m_ref_ok(dollar(x, "evidence"), root))
        add("triage register", AND(m_rows(tri), lambda: all_(vapply_lgl(tri, tri_ok))), "Blocking findings must be repaired; limitation acceptance is owner-reserved")
        e = dollar(receipt, "reproducibility")
        rr = dollar(e, "restore_report")
        restore = m_read(_fpath(root, _str1(dollar(rr, "path")))) if m_ref_ok(rr, root) else None
        add("environment restoration", AND(m_ref_ok(dollar(e, "environment_spec"), root), lambda: identical(dollar(restore, "status"), "PASS"),
                                           lambda: is_true(dollar(restore, "fresh_environment")),
                                           lambda: identical(dollar(restore, "environment_spec"), dollar(e, "environment_spec")),
                                           lambda: m_ref_ok(dollar(restore, "console"), root)),
            "A package list alone is not an environment restoration test")
    return m_checks(body)


M_STAGE_AI_ROLES = {"start": ["independent_reconstruction", "red_team"],
                    "framing": ["framing_builder", "decision_fit_review", "framing_red_team"],
                    "design": ["designer_a", "designer_b", "risk_reviewer"],
                    "finish": ["interpreter", "inference_reviewer", "numerical_auditor"]}
M_STAGE_RECEIPTS = {"start": "artifacts/stage1_decision.json", "framing": "artifacts/stage2_framing.json",
                    "design": "artifacts/stage3_locked_design.json", "execution": "artifacts/stage4_validation_status.json",
                    "finish": "artifacts/stage5_interpretation_status.json"}
M_REVIEW_PRIOR = {"framing": "artifacts/stage1_decision.json", "design": "artifacts/stage2_framing.json",
                  "execution": "artifacts/stage3_locked_design.json", "finish": "artifacts/stage4_validation_status.json"}
M_REVIEW_SUBJECT_PATTERN = {"start": r"^(?!(transcripts|captures|packets|approvals|artifacts/operations)/)", "design": r"^docs/",
                            "execution": r"^(builds/frozen|analysis)/.+\.R$", "finish": r"^docs/.+\.md$"}


def _pth(x):
    return unique([_str1(dollar(z, "path")) for z in m_refs(x) if is_list(z) and m_text(dollar(z, "path"))])


def m_review_subjects(stage, receipt, rp, root=None):
    direct = _pth(receipt)
    pat = M_REVIEW_SUBJECT_PATTERN.get(stage)
    own = [] if pat is None else [p for p in direct if re.search(pat, p)]
    if stage == "execution" and root is not None:
        for p in [d for d in direct if re.search(r"^receipts/[^/]+\.json$", d)]:
            f = _fpath(root, p)
            if os.path.exists(f):
                via = _pth(m_read(f))
                own = unique(own + [v for v in via if re.search(pat, v)])
    if stage in ("execution", "design", "finish") and not own:
        own = [None]
    if stage == "start" and not (any(o is not None and o.startswith("data/") for o in own) and any(o is not None and o.startswith("docs/") for o in own)):
        own = own + [None]
    prior = M_REVIEW_PRIOR.get(stage)
    out = unique(([prior] if prior is not None else []) + own)
    return [o for o in out if o is None or o != rp]


def m_reachable(start, root):
    seen, todo = [], [start]
    while todo:
        ref = todo.pop(0)
        if not m_ref_ok(ref, root):
            continue
        p = _str1(dollar(ref, "path"))
        if p in seen or p.startswith("artifacts/operations/"):
            continue
        seen.append(p)
        if p.lower().endswith(".json"):
            todo.extend(m_refs(m_read(_fpath(root, p))))
    return seen


def _read_lines_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    t = raw.decode("utf-8", "surrogateescape").replace("\r\n", "\n").replace("\r", "\n")
    return t[:-1] if t.endswith("\n") else t


def m_review_coverage(add, root, stage, sends, receipt_path):
    rp = _str1(receipt_path) if m_text(receipt_path) else M_STAGE_RECEIPTS.get(stage)
    rpath = _fpath(root, rp if rp is not None else "NA")
    receipt = m_read(rpath) if (rp is not None and os.path.exists(rpath)) else None
    add(f"review coverage {stage} receipt", is_list(receipt), "The stage receipt defines which reviews are required")
    if not is_list(receipt):
        return
    reached = m_reachable({"path": rp, "sha256": m_hash(rpath)}, root)
    need_replies = unique([p for p in reached if p.startswith(f"transcripts/{stage}/") and re.search(r"_reply(\.|$)", os.path.basename(p))])
    need_roles = list(M_STAGE_AI_ROLES.get(stage, [])) + (["cross_review"] if identical(dollar(receipt, "cross_review"), "PASS") else [])
    if stage == "execution":
        sr = D(m_read(_fpath(root, "artifacts/stage3_locked_design.json")), "methodology", "structural_review", "policy")
        if identical(sr, "required"):
            need_roles.append("structural reviewer")
    rows = sends if m_rows(sends) else []

    def bound(s):
        cap = m_read(_fpath(root, _str1(D(s, "capture", "path")))) if m_ref_ok(dollar(s, "capture"), root) else None
        txt = _read_lines_text(_fpath(root, _str1(D(s, "reply", "path")))) if m_ref_ok(dollar(s, "reply"), root) else ""
        return AND(m_text(dollar(s, "id")), lambda: m_text(dollar(s, "nonce")), lambda: m_ref_ok(dollar(s, "reply"), root), lambda: is_list(cap),
                   lambda: identical(dollar(cap, "send_id"), dollar(s, "id")), lambda: identical(dollar(cap, "reply"), dollar(s, "reply")),
                   lambda: m_text(dollar(cap, "capture_sha256")),
                   lambda: identical(r_tolower(dollar(cap, "capture_sha256")), r_tolower(D(s, "reply", "sha256"))),
                   lambda: OR(dollar(cap, "nonce") is None, lambda: identical(dollar(cap, "nonce"), dollar(s, "nonce"))),
                   lambda: trimws(txt).endswith(f"END_REPLY {_str1(dollar(s, 'id'))} {_str1(dollar(s, 'nonce'))}"))
    subjects = m_review_subjects(stage, receipt, rp, root)
    if need_roles:
        add(f"review coverage {stage} review subjects", len(subjects) > 0 and not any(s is None for s in subjects),
            "The artifacts under review are defined (execution: frozen builder scripts referenced)")
    reach_other = setdiff(reached, [rp])

    def current(s):
        att = dollar(s, "attachments")

        def subj_ok(p):
            if p is None or not os.path.exists(_fpath(root, p)):
                return False

            def a_ok(a):
                return AND(is_list(a), lambda: OR(identical(dollar(a, "path"), p),
                                                  lambda: AND(p.startswith("analysis/"), lambda: m_text(dollar(a, "path")),
                                                              lambda: _str1(dollar(a, "path")).startswith("builds/frozen/"), lambda: m_ref_ok(a, root))),
                           lambda: m_text(dollar(a, "sha256")), lambda: identical(r_tolower(dollar(a, "sha256")), m_hash(_fpath(root, p))))
            return any_(vapply_lgl(att, a_ok))
        return AND(m_rows(att), lambda: length(att) > 0, lambda: m_refs_ok(att, root, False),
                   lambda: any_(vapply_lgl(att, lambda a: AND(is_list(a), lambda: m_text(dollar(a, "path")), lambda: _str1(dollar(a, "path")) in reach_other))),
                   lambda: all_(vapply_lgl(RVec("chr", subjects), lambda p: subj_ok(_str1(p)))))
    prov = dollar(receipt, "ai_provenance") if m_rows(dollar(receipt, "ai_provenance")) else []

    def prov_ok(s, r):
        px = r_filter(lambda x: identical(dollar(x, "role"), r), prov)
        return OR(not len(px), lambda: AND(len(px) == 1, lambda: identical(dollar(px[0], "output"), dollar(s, "reply")),
                                           lambda: identical(dollar(px[0], "provider"), dollar(s, "ai"))))
    for p in need_replies:
        hit = r_filter(lambda s: AND(is_list(dollar(s, "reply")), lambda: identical(D(s, "reply", "path"), p)), rows)
        add(f"review coverage {stage} reply {p}", AND(len(hit) == 1, lambda: bound(hit[0])),
            "Exactly one send captured this required reply, bound by hash, with its own end marker")
    for r in unique(need_roles):
        hit = r_filter(lambda s: AND(identical(dollar(s, "role"), r), lambda: bound(s), lambda: current(s), lambda: prov_ok(s, r)), rows)
        add(f"review coverage {stage} role {r}", len(hit) >= 1,
            "Each required review role has a captured, hash-bound reply from a send that saw current artifacts and matches the recorded provenance")
    for s in _iter(rows):
        add(paste1("review coverage", stage, "capture", dollar(s, "id")), bound(s),
            "Every sent review reply is its own: capture names this send and reply, hash matches, own END_REPLY marker")
    h = []
    for s in _iter(rows):
        rep = dollar(s, "reply")
        if is_list(rep) and m_text(dollar(rep, "sha256")):
            h.append(_str1(dollar(rep, "sha256")).lower())
    ids = vapply_chr(rows, lambda s: dollar(s, "id") if m_text(dollar(s, "id")) else RVec("chr", [None]))
    nonces = vapply_chr(rows, lambda s: dollar(s, "nonce") if m_text(dollar(s, "nonce")) else RVec("chr", [None]))
    add(f"review coverage {stage} unique send ids", None not in ids and not anydup(ids) and None not in nonces and not anydup(nonces),
        "Each send id and nonce appears once in the stage ledger")
    add(f"review coverage {stage} distinct replies", len(h) == len(rows) and not anydup(h), "No reply is reused for another send")


def m_historical(root, stage, sends):
    side = _fpath(root, f"artifacts/operations/{stage}.historical.json")
    h = m_read(side) if os.path.exists(side) else None
    if not is_list(h) or not m_rows(dollar(h, "historical_sends")):
        return []
    out = []
    for e in _iter(dollar(h, "historical_sends")):
        if OR(not is_list(e), lambda: not m_text(dollar(e, "send_id")), lambda: not m_ref_ok(dollar(e, "supersession"), root)):
            continue
        sid = dollar(e, "send_id")
        s = r_filter(lambda x: identical(dollar(x, "id"), sid), sends if m_rows(sends) else [])
        if OR(len(s) != 1, lambda: not m_ref_ok(dollar(s[0], "packet"), root)):
            continue
        d = m_read(_fpath(root, _str1(D(e, "supersession", "path"))))
        named = AND(is_list(d), lambda: OR(identical(dollar(d, "historical_sent_fail"), sid),
                                           lambda: in1(sid, unlist_vec(dollar(d, "historical_sends")))))
        if OR(NOT(named), lambda: not m_ref_ok(dollar(d, "new_candidate"), root), lambda: not is_list(dollar(d, "superseded_inputs")),
              lambda: not length(dollar(d, "superseded_inputs"))):
            continue
        si = dollar(d, "superseded_inputs")
        if not all_(vapply_lgl(si, lambda a: m_ref_ok(a, root))):
            continue
        out.append({"historical": True, "send_id": _str1(sid), "packet_path": D(s[0], "packet", "path"), "map": si})
    return out


def m_hist_resolve(ref, hist, root):
    for h in hist:
        p = dollar(ref, "path")
        if length(p) == 0:
            raise RError("attempt to select less than one element in get1index")
        a = elt(dollar(h, "map"), _str1(p) if _str1(p) is not None else p)
        if AND(is_list(a), lambda: m_text(dollar(ref, "sha256")), lambda: identical(r_tolower(dollar(a, "sha256")), r_tolower(dollar(ref, "sha256"))),
               lambda: m_ref_ok(a, root)):
            return a
    return ref


def m_hist_ref_ok(ref, root, hist):
    return m_ref_ok(ref, root) or m_ref_ok(m_hist_resolve(ref, hist, root), root)


def _set_elem(o, name, value):
    """R `o$name <- value` on a list (value not NULL): replaces the (partially matched) element in place or appends."""
    o = dict(o)
    if name in o:
        o[name] = value
    else:
        o[name] = value
    return o


def m_ops_refs(o, hist):
    hid = [h["send_id"] for h in hist]
    if o is not None and not is_list(o):
        raise RError("invalid (NULL) left side of assignment")
    sends = dollar(o, "sends")
    new = []
    for s in _iter(sends):
        if is_list(s) and isinstance(s, dict) and len([i for i in unique(as_chr_list(values_or_empty(dollar(s, "id")) if not is_list(dollar(s, "id")) else unlist_values(dollar(s, "id")))) if i in hid]) == 1:
            s = {k: v for k, v in s.items() if k != "attachments"}
        new.append(s)
    if o is None:
        o = {"sends": new}
    elif isinstance(o, dict):
        o = _set_elem(o, "sends", new)
    else:
        o = list(o) + [new]
    return m_refs(o)


def m_operations(root, state, stage, final=False, receipt=None):
    def body(add):
        o = m_read(_fpath(root, f"artifacts/operations/{stage}.json"))
        sends = dollar(o, "sends")
        add(f"operations ledger {stage}", AND(is_list(o), lambda: m_rows(sends), lambda: length(sends) > 0), "The stage ledger exists and lists its sends")
        hist = m_historical(root, stage, sends)
        hid = [h["send_id"] for h in hist]
        for s in _iter(sends):
            def att_ok(s=s):
                sid = _str1(dollar(s, "id"))
                if sid in hid:
                    hh = [h for h in hist if h["send_id"] == sid]
                    return all_([m_hist_ref_ok(r, root, hh) for r in m_refs(dollar(s, "attachments"))])
                return m_refs_ok(dollar(s, "attachments"), root, False)
            add(paste1("send identity", dollar(s, "id")),
                AND(m_text(dollar(s, "id")), lambda: m_text(dollar(s, "ai")), lambda: m_text(dollar(s, "nonce")), lambda: m_ref_ok(dollar(s, "packet"), root),
                    att_ok, lambda: m_ref_ok(dollar(s, "reply"), root), lambda: m_ref_ok(dollar(s, "capture"), root)),
                "Preserve exact packet, files, reply and capture record (H1: a declared historical send may bind archived copies of a replaced candidate)")
        m_review_coverage(add, root, stage, sends, receipt)
        sr = dollar(o, "supersession_resolutions")

        def keep(r):
            return AND(is_list(r), lambda: not any_(vapply_lgl(sends, lambda x: identical(D(x, "packet", "path"), dollar(r, "path")))))
        res = r_filter(keep, sr if is_list(sr) else [])
        if length(sr):
            add("supersession resolutions", len(res) == length(sr), "A resolved supersedes target must not be a sent packet in this ledger")
        try:
            closure = m_inventory(m_ops_refs(o, hist), root, res + hist)
        except RError:
            closure = None
        add("operations evidence closure", closure is not None, "At stage completion, reject stale nested packet references, including pre-lock candidates")
    return m_checks(body)


def m_inventory(refs, root, resolutions=None):
    resolutions = list(_iter(resolutions))
    seen = {}
    root = os.path.realpath(root)

    def resolve(ref):
        low = as_character(r_tolower(dollar(ref, "sha256")))
        pre = [mm.group(0) for v in low if v is not None for mm in [re.match(r"^[0-9a-f]+", v)] if mm]
        for r in resolutions:
            dr = dollar(r, "deviation_record")
            d = m_read(_fpath(root, _str1(dollar(dr, "path")))) if (is_list(dr) and m_ref_ok(dr, root)) else None
            if AND(identical(dollar(r, "path"), dollar(ref, "path")), lambda: is_true(dollar(r, "never_sent")), lambda: len(pre) == 1,
                   lambda: len(pre[0]) >= 16, lambda: is_list(d), lambda: identical(dollar(d, "path"), dollar(ref, "path")),
                   lambda: m_text(dollar(d, "sha256")), lambda: len(_str1(dollar(d, "sha256"))) == 64,
                   lambda: _str1(dollar(d, "sha256")).lower().startswith(pre[0]), lambda: is_true(dollar(d, "never_sent"))):
                return {"path": dollar(ref, "path"), "sha256": dollar(d, "sha256")}
        return ref

    resolutions = list(_iter(resolutions))
    hist = [r for r in resolutions if is_true(dollar(r, "historical"))]
    resolutions = [r for r in resolutions if not is_true(dollar(r, "historical"))]

    def visit_all(rs, u):
        for child in _iter(rs):
            visit(child, u)

    def visit(ref, under=()):
        under = list(under)
        ref = dict(ref) if isinstance(ref, dict) else ref
        pv = [v.replace("\\", "/") if v is not None else None for v in as_character(dollar(ref, "path"))]
        if len(pv) == 0:
            raise RError("argument is of length zero")
        if len(pv) > 1:
            raise RError("the condition has length > 1")
        if not isinstance(ref, dict):
            raise RError("unsupported reference container")
        ref["path"] = pv[0]
        if pv[0] is not None and pv[0].startswith(root + "/"):
            ref["path"] = pv[0][len(root) + 1:]
        if not m_ref_ok(ref, root) and len(under):
            ref = m_hist_resolve(ref, under, root)
        if not m_ref_ok(ref, root):
            ref = resolve(ref)
        if not m_ref_ok(ref, root):
            raise RError(f"Missing, unsafe or stale inventory dependency: {_str1(dollar(ref, 'path'))}")
        path = _str1(dollar(ref, "path"))
        if path in seen:
            if not identical(seen[path]["sha256"], dollar(ref, "sha256")):
                raise RError("Conflicting inventory identity")
            return
        seen[path] = {"path": path, "sha256": dollar(ref, "sha256"), "bytes": float(os.path.getsize(_fpath(root, path)))}
        if path.lower().endswith(".json"):
            j = m_read(_fpath(root, path))

            def anchored(h):
                return OR(identical(dollar(h, "packet_path"), path),
                          lambda: AND(is_list(j), lambda: OR(identical(dollar(j, "send_id"), dollar(h, "send_id")), lambda: identical(dollar(j, "id"), dollar(h, "send_id"))),
                                      lambda: is_list(dollar(j, "packet")), lambda: identical(D(j, "packet", "path"), dollar(h, "packet_path"))),
                          lambda: any_(vapply_lgl(dollar(h, "map"), lambda a: AND(identical(dollar(a, "path"), path),
                                                                                lambda: identical(r_tolower(dollar(a, "sha256")), r_tolower(dollar(ref, "sha256")))))))
            u = under + [h for h in hist if _filter_true(anchored(h))]
            if is_list(j) and m_rows(dollar(j, "sends")) and len(hist):
                for sd in _iter(dollar(j, "sends")):
                    visit_all(m_refs(sd), u + [h for h in hist if is_list(sd) and identical(h["send_id"], dollar(sd, "id"))])
                if isinstance(j, dict):
                    k = "sends" if "sends" in j else [x for x in j if x.startswith("sends")][0]
                    j = {a: b for a, b in j.items() if a != k}
            visit_all(m_refs(j), u)

    for ref in _iter(refs):
        visit(ref)
    if not seen:  # R: order(names(list())) -> order(NULL) -> "argument 1 is not a vector"
        raise RError("argument 1 is not a vector")
    return [seen[k] for k in sorted(seen)]


def m_missing_values(rule):
    mv = elt(rule, "missing_values")
    return unlist_vec(mv if mv is not None else elt(rule, "missing_value"))


def m_missing_rule(rule, plan):
    mv = lambda: m_missing_values(rule)  # noqa: E731
    return AND(is_list(rule), lambda: m_text(dollar(rule, "flag_field")),
               lambda: in1(dollar(rule, "flag_field"), unlist_vec(dollar(plan, "exact_fields"))),
               lambda: (elt(rule, "missing_value") is None) != (elt(rule, "missing_values") is None),
               lambda: length(mv()) > 0, lambda: is_character(mv()),
               lambda: not any_na(mv()), lambda: all(nzchar(v) for v in values(mv())),
               lambda: not anydup(values(mv())), lambda: m_text(dollar(rule, "present_value")),
               lambda: NOT(in1(dollar(rule, "present_value"), mv())),
               lambda: is_character(dollar(rule, "missing_token")), lambda: length(dollar(rule, "missing_token")) == 1,
               lambda: not scalar_na(dollar(rule, "missing_token")),
               lambda: in1(dollar(rule, "missing_token"), RVec("chr", ["", "null", "NA"])))


def m_checkpoint_contract(s3):
    def body(add):
        meth = dollar(s3, "methodology")
        rules_out = D(meth, "operational", "checkpoint_output_rules")
        cps = dollar(meth, "checkpoints")
        expected = []
        for p in _iter(cps):
            nf = dollar(p, "numeric_fields")
            if length(nf):
                expected.extend(paste(dollar(p, "id"), unlist_vec(nf), sep=":"))
        add("checkpoint output schema coverage",
            AND(m_rows(rules_out), lambda: m_equal_ids(rlapply(rules_out, lambda r: chr_vec(paste(dollar(r, "checkpoint_id"), dollar(r, "field"), sep=":"))), as_list_chr(expected))),
            "Lock authoritative output nullability for every numeric checkpoint column")
        for p in _iter(cps):
            numeric = unlist_vec(dollar(p, "numeric_fields"))
            declarations = dollar(p, "field_nullability")
            rules = dollar(p, "numeric_missingness")
            add(paste1("checkpoint nullability", dollar(p, "id")),
                OR(AND(not length(numeric), lambda: declarations is None),
                   lambda: AND(is_list(declarations), lambda: setequal(chr_or_null(names(declarations)), numeric),
                               lambda: not anydup(names(declarations) or []),
                               lambda: all_(vapply_lgl(declarations, lambda x: AND(is_logical(x), lambda: length(x) == 1, lambda: not scalar_na(x)))))),
                "Every numeric checkpoint field explicitly declares nullable true/false")
            for f in values_or_empty(numeric):
                def m_ok(r, f=f, p=p):
                    return AND(identical(dollar(r, "checkpoint_id"), dollar(p, "id")), lambda: identical(dollar(r, "field"), f))
                ml = r_filter(m_ok, rules_out)
                nb = lambda ml=ml: dollar(ml[0], "nullable")  # noqa: E731
                add(paste1("output/checkpoint compatibility", dollar(p, "id"), f),
                    AND(len(ml) == 1, lambda: is_logical(nb()), lambda: length(nb()) == 1, lambda: not scalar_na(nb()),
                        lambda: identical(nb(), elt(declarations, f))),
                    "Checkpoint nullability must match the authoritative output schema")
            if is_list(declarations):
                kept = {k: v for k, v in declarations.items() if is_true(v)} if isinstance(declarations, dict) else None
                nullable = None if kept is None else list(kept.keys())
            else:
                nullable = []
            add(paste1("checkpoint missingness contract", dollar(p, "id")),
                AND(setequal(chr_or_null(names(rules)), chr_or_null(nullable)), lambda: all_(vapply_lgl(rules, lambda r: m_missing_rule(r, p)))),
                "Nullable fields need an exact status flag and a nonnumeric missing token; finite-only fields cannot opt out")
    return m_checks(body)


def m_source(s3, s4, root):
    def body(add):
        kind = D(s3, "methodology", "operational", "source_contract", "kind")
        ssg = dollar(s4, "sql_source_gate")
        add("SQL applicability", OR(AND(identical(kind, "sql"), lambda: identical(ssg, "PASS")),
                                    lambda: AND(identical(kind, "file"), lambda: identical(ssg, "NOT_APPLICABLE"))),
            "N/A is restricted to a locked file-only source")
        ref = D(s4, "evidence_receipts", "source")
        r = m_read(_fpath(root, _str1(dollar(ref, "path")))) if m_ref_ok(ref, root) else None
        add("source fidelity", AND(identical(dollar(r, "status"), "PASS"), lambda: identical(dollar(r, "source_kind"), kind),
                                   lambda: identical(dollar(r, "sql_extraction_used"), identical(kind, "sql")),
                                   lambda: identical(D(r, "fidelity_check", "status"), "PASS"),
                                   lambda: m_ref_ok(D(r, "fidelity_check", "report"), root)),
            "Non-SQL inputs still require actual source identity/fidelity evidence")
    return m_checks(body)


def m_relative_path(path, root):
    path = path.replace("\\", "/")
    root = re.sub(r"/+$", "", root.replace("\\", "/"))
    if not path.lower().startswith(root.lower() + "/"):
        raise RError("Path is outside project root")
    rel = path[len(root) + 1:]
    if any(seg in ("", ".", "..") for seg in strsplit_fixed(rel, "/")):
        raise RError("Unsafe relative path")
    return rel
