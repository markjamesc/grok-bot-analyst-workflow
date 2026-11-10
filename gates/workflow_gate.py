"""Python port of workflow-gate/workflow_gate.R (Five-Stage Workflow Gate, Stage 4 -> Stage 5 release).

Same inputs (artifacts/stage1..4 receipts), same check list, same report fields, same exit status:
0 = PASS, 1 = FAIL. Where the R script would stop with an R error (no report written), this port
also writes no report and exits 1 (reported as TOOL_ERROR by the wrapper in gates.common).

Usage: python3 -m gates.workflow_gate [project_root] [--dry-run]
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import sys
import tempfile

from . import methodology as M
from .rsem import (AND, OR, RError, RVec, DataFrame, D, all_, any_na, as_character, as_numeric, dollar, elt, identical,
                   in_, is_character, is_data_frame, is_list, is_numeric, is_true, length, names, read_json_file, setequal,
                   sha256_file, simplify, trimws, values, scalar_na)

ROLES = ["source", "fixtures", "reconciliation", "structural", "validation", "lineage", "methodology"]


def _text_scalar(x):
    s = M._str1(x)
    return s is not None and len(trimws(s)) > 0


def _enum(x, vals):
    return _text_scalar(x) and M._str1(x) in vals


def _nonempty_strings(x):
    if not is_character(x) or length(x) == 0:
        return False
    vs = values(x)
    return not any(v is None for v in vs) and all(len(trimws(v)) > 0 for v in vs)


def _has_fields(x, fields):
    if x is None:
        return False
    nm = names(x) or []
    return all(f in nm for f in fields)


def _is_value(x, field, expected):
    return x is not None and field in (names(x) or []) and as_character(elt(x, field)) == as_character(expected)


def _paste0(*parts):
    vecs = [as_character(p) for p in parts]
    if all(not v for v in vecs):
        return ""
    n = max(len(v) for v in vecs)
    vecs = [v if v else [""] for v in vecs]
    out = ["".join("NA" if v[i % len(v)] is None else v[i % len(v)] for v in vecs) for i in range(n)]
    return out[0] if len(out) == 1 else out


def _eq_all(a, b):
    """all(a == b) for two data.frame columns (R coercion), True/False/None."""
    if not isinstance(a, RVec) or not isinstance(b, RVec) or len(a.v) != len(b.v):
        raise RError("comparison of these types is not implemented")
    chr_ = "chr" in (a.type, b.type)
    res = True
    for x, y in zip(a.v, b.v):
        if x is None or y is None:
            res = None if res is not False else res
            continue
        if chr_:
            eq = as_character(x)[0] == as_character(y)[0]
        else:
            eq = float(x) == float(y)
        if not eq:
            return False
    return res


def run(project_root, write=True):
    """Returns (exit_status, report_or_None, checks). Raises nothing: R errors -> (1, None, checks_so_far)."""
    checks = []

    def add_check(name, ok, detail):
        checks.append({"check": name, "result": "PASS" if ok is True else "FAIL", "detail": detail})

    project_root = os.path.realpath(project_root) if os.path.exists(project_root) else os.path.abspath(project_root)
    artifacts = f"{project_root}/artifacts"
    paths = {"stage1": f"{artifacts}/stage1_decision.json", "stage2": f"{artifacts}/stage2_framing.json",
             "stage3": f"{artifacts}/stage3_locked_design.json", "stage4": f"{artifacts}/stage4_validation_status.json",
             "gate": f"{artifacts}/workflow_gate_status.json"}

    def read_json_safe(path, label):
        if not os.path.exists(path):
            add_check(f"{label} artifact exists", False, f"Missing: {path}")
            return None
        try:
            out = simplify(read_json_file(path))
            if not is_list(out) or is_data_frame(out) or names(out) is None:
                raise RError("Expected a JSON object")
        except RError as e:
            add_check(f"{label} artifact parses", False, str(e))
            return None
        add_check(f"{label} artifact exists", True, path)
        add_check(f"{label} artifact parses", True, "Valid JSON")
        return out

    try:
        stage1 = read_json_safe(paths["stage1"], "Stage 1")
        stage2 = read_json_safe(paths["stage2"], "Stage 2")
        stage3 = read_json_safe(paths["stage3"], "Stage 3")
        stage4 = read_json_safe(paths["stage4"], "Stage 4")

        req1 = ["stage", "status", "decision_statement", "decision_owner"]
        add_check("Stage 1 required fields", _has_fields(stage1, req1), "Required: " + ", ".join(req1))
        add_check("Stage 1 locked", _is_value(stage1, "status", "LOCKED"), "status must equal LOCKED")
        req2 = ["stage", "status", "analytical_question"]
        add_check("Stage 2 required fields", _has_fields(stage2, req2), "Required: " + ", ".join(req2))
        add_check("Stage 2 locked", _is_value(stage2, "status", "LOCKED"), "status must equal LOCKED")
        req3 = ["stage", "status", "design_version", "population", "grain", "window_start", "window_end", "decision_rules", "required_outputs"]
        add_check("Stage 3 required fields", _has_fields(stage3, req3), "Required: " + ", ".join(req3))
        add_check("Stage 3 locked", _is_value(stage3, "status", "LOCKED"), "status must equal LOCKED")
        req4 = ["stage", "status", "design_version_used", "sql_source_gate", "fixtures", "r_a_status", "r_b_status", "reconciliation",
                "validation_gate", "unresolved_issues"]
        add_check("Stage 4 required fields", _has_fields(stage4, req4), "Required: " + ", ".join(req4))
        if stage3 is not None and stage4 is not None and "design_version" in names(stage3) and "design_version_used" in names(stage4):
            same = as_character(dollar(stage3, "design_version")) == as_character(dollar(stage4, "design_version_used"))
            add_check("Stage 4 used locked Stage 3 version", same,
                      _paste0("Stage 3=", dollar(stage3, "design_version"), "; Stage 4=", dollar(stage4, "design_version_used")))
        else:
            add_check("Stage 4 used locked Stage 3 version", False, "Version fields unavailable")
        for field in ["fixtures", "r_a_status", "r_b_status", "reconciliation", "validation_gate"]:
            add_check(f"Stage 4 {field}", _is_value(stage4, field, "PASS"), f"{field} must equal PASS")
        ui = dollar(stage4, "unresolved_issues") if stage4 is not None else None
        issues_ok = AND(stage4 is not None, lambda: "unresolved_issues" in names(stage4),
                        lambda: RVec("lgl", [v is not None and not math.isnan(v) for v in as_numeric(ui)]) if length(as_numeric(ui)) != 1 else (as_numeric(ui)[0] is not None and not math.isnan(as_numeric(ui)[0])),
                        lambda: RVec("lgl", [None if v is None else v == 0 for v in as_numeric(ui)]) if length(as_numeric(ui)) != 1 else (None if as_numeric(ui)[0] is None else as_numeric(ui)[0] == 0))
        add_check("Stage 4 unresolved issues", issues_ok, "unresolved_issues must equal 0")
        add_check("Stage 4 overall status", _is_value(stage4, "status", "PASS"), "status must equal PASS")

        add_check("Capacity stance explicit", _enum(dollar(stage2, "capacity_stance"), ["unordered_ok", "hard_attention_budget"]), "Explicit Stage 2 enum required")
        add_check("ML mode explicit", _enum(dollar(stage3, "ml_mode"), ["None", "A", "B"]), "Explicit Stage 3 enum required")
        if identical(dollar(stage2, "capacity_stance"), "hard_attention_budget"):
            ranking = dollar(stage3, "ranking_contract")

            def n_ok():
                n = dollar(ranking, "n")
                if not is_numeric(n) or length(n) != 1:
                    return False
                v = values(n)[0]
                return v is not None and math.isfinite(float(v)) and v >= 1 and float(v) == math.floor(float(v))
            add_check("Ranking contract locked",
                      AND(is_list(ranking), lambda: _text_scalar(dollar(ranking, "key")), lambda: _text_scalar(dollar(ranking, "tie_break")),
                          lambda: _text_scalar(dollar(ranking, "capacity_unit")), lambda: is_true(dollar(ranking, "membership_first")),
                          lambda: identical(dollar(ranking, "padding_allowed"), False),
                          lambda: OR(is_true(dollar(ranking, "owner_n_deferred")), n_ok)),
                      "Budget requires key, tie-break, unit, membership-first, no padding and N or explicit owner deferral")
        design_v3 = M.m_read(paths["stage3"])
        execution_v3 = M.m_read(paths["stage4"])
        policy = D(design_v3, "methodology", "structural_review")
        skip_structural = AND(identical(dollar(stage4, "structural_cross_review"), "NOT_REQUIRED"), lambda: identical(dollar(policy, "policy"), "conditional"),
                              lambda: M.m_equal_ids(dollar(policy, "fixture_covered_rule_ids"), D(design_v3, "methodology", "judged_rule_ids")),
                              lambda: M.m_text(dollar(stage4, "structural_review_reason")))
        add_check("Structural cross-review disposition", OR(_is_value(stage4, "structural_cross_review", "PASS"), skip_structural),
                  "PASS for executed review or justified NOT_REQUIRED with complete locked fixture coverage")
        add_check("Fixture identity", AND(_text_scalar(dollar(stage3, "fixture_version")),
                                          lambda: identical(dollar(stage3, "fixture_version"), dollar(stage4, "fixture_version_used"))),
                  "Frozen fixture version must match")
        model_required = identical(dollar(stage3, "ml_mode"), "A")
        add_check("Model requirement matches ML mode", identical(dollar(stage4, "decision_critical_model_required"), model_required),
                  "Mode A requires a decision-critical model; None/B do not")
        add_check("Model validation matches ML mode",
                  identical(dollar(stage4, "decision_critical_model_validation"), "PASS") if model_required
                  else identical(dollar(stage4, "decision_critical_model_validation"), "NOT_REQUIRED"),
                  "Mode A requires PASS; None/B require NOT_REQUIRED for the judged path")
        roles = ROLES + (["model"] if model_required else [])
        manifest = dollar(stage4, "evidence_receipts")
        verified = {}
        add_check("Evidence receipt roles", AND(is_list(manifest), lambda: all(r in (names(manifest) or []) for r in roles)),
                  "All required receipt roles must be declared")
        if not os.path.exists(project_root):
            raise RError("path[1] does not exist")
        root_normal = os.path.realpath(project_root)
        for role in roles:
            entry = elt(manifest, role) if is_list(manifest) else None

            def safe_fn():
                p, s = dollar(entry, "path"), dollar(entry, "sha256")
                return AND(is_list(entry), lambda: _text_scalar(p), lambda: _text_scalar(s),
                           lambda: bool(re.search(r"^[a-fA-F0-9]{64}$", M._str1(s))),
                           lambda: not re.search(r"^(/|[A-Za-z]:|\\)", M._str1(p)),
                           lambda: ".." not in M.strsplit_fixed(M._str1(p).replace("\\", "/"), "/"))
            safe = safe_fn() if is_list(entry) else False
            fpath = f"{project_root}/{M._str1(dollar(entry, 'path'))}" if safe else ""
            if safe:
                safe = (os.path.exists(fpath) and not os.path.isdir(fpath) and os.path.realpath(fpath).startswith(root_normal + "/")
                        and (os.path.getsize(fpath) > 0))
            hash_ok = bool(safe) and M._str1(dollar(entry, "sha256")).lower() == sha256_file(fpath)
            add_check(f"Receipt hash {role}", hash_ok, "Nonempty local receipt and exact SHA-256 required")
            if not hash_ok:
                continue
            try:
                receipt = simplify(read_json_file(fpath))
            except RError:
                receipt = None
            if not is_list(receipt) or is_data_frame(receipt) or names(receipt) is None:
                add_check(f"Receipt object {role}", False, "Expected a JSON object")
                continue
            metadata_ok = AND(is_list(receipt),
                              lambda: OR(identical(dollar(receipt, "status"), "PASS"),
                                         lambda: AND(role == "structural", skip_structural, lambda: identical(dollar(receipt, "status"), "NOT_REQUIRED"))),
                              lambda: identical(dollar(receipt, "design_version"), dollar(stage3, "design_version")),
                              lambda: identical(dollar(receipt, "fixture_version"), dollar(stage3, "fixture_version")),
                              lambda: _text_scalar(dollar(receipt, "checked_at_utc")))
            add_check(f"Receipt metadata {role}", metadata_ok, "PASS, design/fixture identities and timestamp required")
            if role == "reconciliation":
                critical = dollar(stage3, "reconciliation_critical_fields")

                def rc_ok():
                    rc = dollar(receipt, "row_count")
                    mc = dollar(receipt, "mismatch_count")
                    return AND(is_list(receipt), lambda: _nonempty_strings(critical), lambda: _nonempty_strings(dollar(receipt, "fields")),
                               lambda: setequal(critical, dollar(receipt, "fields")),
                               lambda: is_numeric(mc), lambda: identical(RVec("dbl", as_numeric(mc)) if length(mc) != 1 else as_numeric(mc)[0], 0.0),
                               lambda: is_numeric(rc), lambda: length(rc) == 1, lambda: values(rc)[0] is not None,
                               lambda: math.isfinite(float(values(rc)[0])), lambda: values(rc)[0] >= 0,
                               lambda: float(values(rc)[0]) == math.floor(float(values(rc)[0])))
                add_check("Reconciliation scorecard", rc_ok(), "All locked fields and zero mismatches required")
            if role == "fixtures":
                cases = dollar(receipt, "cases")

                def fx_ok():
                    return AND(is_data_frame(cases), lambda: cases.nrow > 0,
                               lambda: all(c in cases.cols for c in ["id", "expected", "observed_a", "observed_b"]),
                               lambda: _nonempty_strings(dollar(cases, "id")), lambda: not M.anydup(values(dollar(cases, "id"))),
                               lambda: _nonempty_strings(dollar(stage3, "fixture_ids")), lambda: setequal(dollar(cases, "id"), dollar(stage3, "fixture_ids")),
                               lambda: not any_na(cases), lambda: _eq_all(dollar(cases, "expected"), dollar(cases, "observed_a")),
                               lambda: _eq_all(dollar(cases, "expected"), dollar(cases, "observed_b")))
                add_check("Fixture scorecard", fx_ok(), "Every frozen fixture must match expected in both paths")
            if role == "lineage":
                add_check("Lineage contents", AND(is_list(receipt), lambda: _text_scalar(dollar(receipt, "source_snapshot")),
                                                  lambda: _text_scalar(dollar(receipt, "extract_identity")),
                                                  lambda: _nonempty_strings(dollar(receipt, "script_versions"))),
                          "Source snapshot, extract identity and script versions required")
            verified[role] = entry
        checks.extend(M.m_design(design_v3, M.m_read(paths["stage2"]), M.m_read(paths["stage1"]), project_root))
        checks.extend(M.m_execution(design_v3, execution_v3, project_root))
        checks.extend(M.m_ai(dollar(execution_v3, "ai_provenance"), ["R-A", "R-B"], project_root, "execution"))
        for entry in M._iter(dollar(execution_v3, "evidence_receipts")):
            if M.m_ref_ok(entry, project_root):
                for ref in M.m_refs(M.m_read(f"{project_root}/{M._str1(dollar(entry, 'path'))}")):
                    verified[_paste0("dependency:", dollar(ref, "path"))] = ref
        for ref in M.m_refs(dollar(execution_v3, "ai_provenance")):
            verified[_paste0("ai:", dollar(ref, "path"))] = ref
    except RError as e:
        sys.stderr.write(f"Error: {e}\nExecution halted\n")
        return 1, None, checks

    all_pass = len(checks) > 0 and all(c["result"] == "PASS" for c in checks)
    report = {"contract_version": "methodology-v3", "design_version": dollar(stage3, "design_version"),
              "fixture_version": dollar(stage3, "fixture_version"), "evidence_receipts": verified,
              "gate": "five_stage_workflow_gate", "result": "PASS" if all_pass else "FAIL", "stage5_allowed": all_pass,
              "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
              "project_root": project_root, "checks": checks, "implementation": "python-port"}
    if write:
        os.makedirs(f"{artifacts}/workflow-attempts", exist_ok=True)
        fd, attempt = tempfile.mkstemp(prefix="attempt-", suffix=".json", dir=f"{artifacts}/workflow-attempts")
        os.close(fd)
        report["attempt_id"] = os.path.basename(attempt)
        for p in (attempt, paths["gate"]):
            with open(p, "w", encoding="utf-8") as f:
                json.dump(to_json(report), f, indent=2, ensure_ascii=False)
                f.write("\n")
    return (0 if all_pass else 1), report, checks


def to_json(x):
    """R value -> JSON-able python (auto_unbox)."""
    if isinstance(x, RVec):
        return [to_json(v) for v in x.v] if len(x.v) != 1 else x.v[0]
    if isinstance(x, DataFrame):
        return [{k: to_json(c.v[i] if isinstance(c, RVec) else c[i]) for k, c in x.cols.items()} for i in range(x.nrow)]
    if isinstance(x, dict):
        return {k: to_json(v) for k, v in x.items()}
    if isinstance(x, list):
        return [to_json(v) for v in x]
    return x


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    root = argv[0] if argv else os.getcwd()
    status, report, checks = run(root, write=not dry)
    print("\nFive-Stage Workflow Gate (Python)\n========================")
    for c in checks:
        print(f"{c['check'] if isinstance(c['check'], str) else c['check'].v!s:<46} {c['result']}")
    print("------------------------")
    print("OVERALL:", report["result"] if report else "TOOL_ERROR")
    return status


if __name__ == "__main__":
    sys.exit(main())
