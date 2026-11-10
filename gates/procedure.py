"""Python port of procedure-gate/procedure_gate.R (R Procedure Gate: start/begin/complete/amend/status/finalize/successor).

Same state file, same receipts, same checks and statuses. `complete execution` runs the Python
workflow gate (gates.workflow_gate) where the R gate ran workflow_gate.R.

The framework root (where procedure.json and the controlling documents live) defaults to
$GATES_FRAMEWORK_ROOT. Parity tests point it at the R repo so both gates hash the same files.

Usage: python3 -m gates.procedure <action> <project-root> [...]   (same arguments as the R gate)
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

from . import methodology as M
from . import workflow_gate as WG
from .rsem import RError, RVec, as_character, as_numeric, dollar, elt, identical, is_list, is_numeric, length, names, values

FRAMEWORK_ROOT = os.environ.get("GATES_FRAMEWORK_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXTRA_FRAMEWORK_FILES = [p for p in os.environ.get("GATES_EXTRA_FRAMEWORK_FILES", "").split(":") if p]


class Stop(Exception):
    """R stop(): the command exits with status 1 and prints no JSON."""


def _s(x):
    return M._str1(x)


def nz(x, y):
    return y if x is None else x


def paths(project_root):
    if not os.path.exists(project_root):
        raise Stop(f"path[1]=\"{project_root}\": No such file or directory")
    root = os.path.realpath(project_root)
    return {"project_root": root, "procedure_file": f"{FRAMEWORK_ROOT}/procedure-gate/procedure.json",
            "procedure_dir": f"{root}/artifacts/procedure", "checks_dir": f"{root}/artifacts/procedure/checks",
            "state": f"{root}/artifacts/procedure/run_state.json", "certificate": f"{root}/artifacts/final_certificate.json",
            "workflow_report": f"{root}/artifacts/workflow_gate_status.json",
            "workflow_console": f"{root}/artifacts/procedure/checks/execution-workflow-gate-console.txt"}


def sha256_file(p):
    return M.m_hash(p)


def timestamp_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_scalar(x):
    s = _s(x)
    return s is not None and len(s.strip(" \t\r\n")) > 0


def is_value(x, field, expected):
    return is_list(x) and field in (names(x) or []) and as_character(elt(x, field)) == as_character(expected)


def has_fields(x, fields):
    return is_list(x) and all(f in (names(x) or []) for f in fields)


def read_json(path):
    try:
        return M.read_json_file(path)
    except RError as e:
        raise Stop(str(e))


def write_json_atomic(value, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(WG.to_json(value), f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def closure_resolutions(root, step_ids):
    out = []
    for i in step_ids:
        p = f"{root}/artifacts/operations/{i}.json"
        o = M.m_read(p) if os.path.exists(p) else None
        if not is_list(o) or not is_list(dollar(o, "supersession_resolutions")):
            continue
        for r in M._iter(dollar(o, "supersession_resolutions")):
            if is_list(r) and not any(identical(M.D(x, "packet", "path"), dollar(r, "path")) for x in M._iter(dollar(o, "sends"))):
                out.append(r)
    return out


def closure_hist(root, step_ids):
    out = []
    for i in step_ids:
        try:
            o = M.m_read(f"{root}/artifacts/operations/{i}.json")
            if is_list(o):
                out.extend(M.m_historical(root, i, dollar(o, "sends")))
        except RError:
            pass
    return out


def step_closure(root, step_id, receipt):
    try:
        h = closure_hist(root, [step_id])
        refs = M.m_refs({"receipt": receipt}) + M.m_ops_refs(M.m_read(f"{root}/artifacts/operations/{step_id}.json"), h)
        return M.m_inventory(refs, root, closure_resolutions(root, [step_id]) + h)
    except RError:
        return None


def read_procedure():
    return read_json(f"{FRAMEWORK_ROOT}/procedure-gate/procedure.json")


def read_state(root):
    p = paths(root)
    if not os.path.exists(p["state"]):
        raise Stop(f"Procedure run has not been started: {p['state']}")
    return read_json(p["state"])


def save_state(state, root):
    write_json_atomic(state, paths(root)["state"])


def step_by_id(procedure, step_id):
    matches = [s for s in M._iter(dollar(procedure, "steps")) if identical(dollar(s, "id"), step_id)]
    if not matches:
        raise Stop(f"Unknown procedure step: {step_id}")
    if len(matches) > 1:
        raise Stop(f"Duplicate procedure step: {step_id}")
    return matches[0]


def completed_ids(state):
    return nz(names(nz(dollar(state, "completed_steps"), [])), [])


def project_path_ok(path):
    if not text_scalar(path):
        return False
    p = _s(path)
    return not re.search(r"^(/|[A-Za-z]:|\\)", p) and not any(seg in ("", ".", "..") for seg in M.strsplit_fixed(p.replace("\\", "/"), "/"))


def resolve_project_path(path, root):
    r = os.path.realpath(root)
    return os.path.realpath(f"{r}/{path.replace(chr(92), '/')}").lower()


def project_file_ok(path, root):
    if not text_scalar(path):
        return False
    p = _s(path)
    if re.search(r"^(/|[A-Za-z]:|\\)", p) or ".." in M.strsplit_fixed(p.replace("\\", "/"), "/"):
        return False
    r = os.path.realpath(root)
    f = f"{r}/{p}"
    if not os.path.exists(f) or os.path.isdir(f) or os.path.getsize(f) == 0:
        return False
    return os.path.realpath(f).startswith(r + "/")


def verify_file_manifest(manifest, root):
    if not is_list(manifest) or length(manifest) == 0:
        return False
    for e in M._iter(manifest):
        if not (is_list(e) and project_file_ok(dollar(e, "path"), root) and text_scalar(dollar(e, "sha256"))
                and _s(dollar(e, "sha256")).lower() == sha256_file(f"{root}/{_s(dollar(e, 'path'))}")):
            return False
    return True


def read_artifact_safe(path):
    if not os.path.exists(path) or os.path.isdir(path) or os.path.getsize(path) <= 0:
        return None
    try:
        v = M.read_json_file(path)
    except RError:
        return None
    if not is_list(v) or names(v) is None:
        return None
    return v


def verify_supporting_evidence(root):
    report = read_artifact_safe(paths(root)["workflow_report"])
    return is_list(report) and verify_file_manifest(dollar(report, "evidence_receipts"), root)


def verify_amendment_history(state, root):
    history = nz(dollar(state, "amendment_history"), [])
    if length(history) == 0:
        return True

    def file_matches(rec):
        return (is_list(rec) and project_file_ok(dollar(rec, "path"), root) and text_scalar(dollar(rec, "sha256"))
                and _s(dollar(rec, "sha256")).lower() == sha256_file(f"{root}/{_s(dollar(rec, 'path'))}"))
    for e in M._iter(history):
        if not is_list(e) or not file_matches(dollar(e, "superseded")) or not file_matches(dollar(e, "change_record")):
            return False
        ch = read_artifact_safe(f"{root}/{_s(M.D(e, 'change_record', 'path'))}")
        if not (is_list(dollar(e, "new")) and is_value(ch, "change_id", dollar(e, "change_id")) and is_value(ch, "step", dollar(e, "step"))
                and is_value(ch, "superseded_sha256", M.D(e, "superseded", "sha256")) and is_value(ch, "new_sha256", M.D(e, "new", "sha256"))
                and is_value(ch, "archive_path", M.D(e, "superseded", "path"))):
            return False
    hl = M._iter(history)
    steps = M.unique([_s(dollar(e, "step")) for e in hl])
    for sid in steps:
        chain = [e for e in hl if identical(dollar(e, "step"), sid)]
        links = len(chain) == 1 or all(identical(M.D(chain[i], "superseded", "sha256"), M.D(chain[i - 1], "new", "sha256")) for i in range(1, len(chain)))
        if not (sid in completed_ids(state) and links and
                identical(M.D(chain[-1], "new", "sha256"), M.D(elt(dollar(state, "completed_steps"), sid), "artifact", "sha256"))):
            return False
    ids = [_s(dollar(e, "change_id")) for e in hl]
    return not M.anydup(ids)


def verify_completed_artifacts(state, root):
    completed = nz(dollar(state, "completed_steps"), [])
    pred = dollar(state, "predecessor")
    if pred is not None:
        refs = [dollar(pred, "state"), dollar(pred, "change_record")]
        if dollar(pred, "certificate") is not None:
            refs.append(dollar(pred, "certificate"))
        if not verify_file_manifest(refs, root):
            return False
    if length(completed) == 0:
        return True
    r = os.path.realpath(root)
    for v in M._iter(completed):
        rel = nz(M.D(v, "artifact", "path"), "")
        exp = nz(M.D(v, "artifact", "sha256"), "")
        p = f"{r}/{_s(rel) if _s(rel) is not None else ''}"
        if not (text_scalar(rel) and text_scalar(exp) and os.path.exists(p) and not os.path.isdir(p) and _s(exp).lower() == sha256_file(p)):
            return False
    for v in M._iter(completed):
        sf, ec = dollar(v, "supporting_files"), dollar(v, "evidence_closure")
        if not ((not length(sf) or verify_file_manifest(sf, root)) and (not length(ec) or verify_file_manifest(ec, root))):
            return False
    return verify_amendment_history(state, root)


def verify_workflow_report(state, root):
    wg = dollar(state, "workflow_gate")
    if wg is None:
        return True
    p = paths(root)["workflow_report"]
    exp = nz(dollar(wg, "report_sha256"), "")
    return text_scalar(exp) and os.path.exists(p) and _s(exp).lower() == sha256_file(p)


CONTROL_FILES = ["docs/MASTER_PROMPT.md", None, "docs/r-workflow-gate-enforcement.md", "workflow-gate/workflow_gate.R",
                 "procedure-gate/procedure_gate.R", "methodology/contracts.R", "methodology/tools.R", "methodology/schema.json",
                 "docs/METHODOLOGY_HARDENING.md", "docs/SEND_QUEUE_PROTOCOL.md", "tools/acceptance.py", "methodology/operations.schema.json",
                 "docs/framework-refinement/LIVE_FAILURE_REPAIRS.md", "tools/run_restore.R"]


def framework_hashes(procedure):
    files = []
    for f in CONTROL_FILES:
        if f is None:
            files.extend(_s(dollar(s, "framework")) for s in M._iter(dollar(procedure, "steps")))
        else:
            files.append(f)
    files = M.unique(files + EXTRA_FRAMEWORK_FILES)
    out = {}
    for rel in files:
        p = f"{FRAMEWORK_ROOT}/{rel}"
        if not os.path.exists(p):
            raise Stop(f"Controlling file is missing: {rel}")
        out[rel] = {"path": rel, "sha256": sha256_file(p)}
    return out


def verify_framework_hashes(state):
    pp = f"{FRAMEWORK_ROOT}/procedure-gate/procedure.json"
    ok = os.path.exists(pp) and (nz(_s(dollar(state, "procedure_sha256")), "")).lower() == sha256_file(pp)
    locked = nz(dollar(state, "framework_hashes"), [])
    if length(locked) == 0 or not ok:
        return False
    return all(os.path.exists(f"{FRAMEWORK_ROOT}/{_s(dollar(e, 'path'))}") and identical(M.r_tolower(dollar(e, "sha256")), sha256_file(f"{FRAMEWORK_ROOT}/{_s(dollar(e, 'path'))}"))
               for e in M._iter(locked))


def check_result(name, ok, detail):
    return {"check": name, "result": "PASS" if ok is True else "FAIL", "detail": detail}


def checks_pass(checks):
    return len(checks) > 0 and all(identical(c.get("result"), "PASS") for c in checks)


def save_checks(root, step_id, phase, checks, context=None):
    p = paths(root)
    os.makedirs(p["checks_dir"], exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=f"{step_id}-{phase}-", suffix=".json", dir=p["checks_dir"])
    os.close(fd)
    record = {"step": step_id, "phase": phase, "result": "PASS" if checks_pass(checks) else "FAIL", "checked_at_utc": timestamp_utc(),
              "context": context, "checks": checks, "attempt_id": os.path.basename(path)}
    write_json_atomic(record, path)
    return {"path": path, "sha256": sha256_file(path), "result": record["result"]}


def _num0(x):
    """identical(as.numeric(x), 0)."""
    v = as_numeric(x)
    return len(v) == 1 and v[0] is not None and v[0] == 0


def validate_stage_receipt(step_id, receipt, root):
    checks = []

    def add(n, ok, d):
        checks.append(check_result(n, ok, d))
    if step_id == "start":
        req = ["stage", "status", "decision_statement", "decision_owner", "ai2_independent_reconstruction", "ai3_independent_red_team",
               "start_gate", "stakeholder_confirmation", "human_analyst_approval", "unresolved_issues"]
        add("Stage 1 required fields", has_fields(receipt, req), ", ".join(req))
        add("Stage 1 number", is_value(receipt, "stage", 1), "stage must equal 1")
        add("Stage 1 locked", is_value(receipt, "status", "LOCKED"), "status must equal LOCKED")
        for f in ["ai2_independent_reconstruction", "ai3_independent_red_team", "start_gate"]:
            add(f"Stage 1 {f}", is_value(receipt, f, "PASS"), f"{f} must equal PASS")
        add("Stakeholder confirmation", is_value(receipt, "stakeholder_confirmation", "CONFIRMED"), "stakeholder_confirmation must equal CONFIRMED")
        add("Stage 1 human approval", is_value(receipt, "human_analyst_approval", "APPROVED"), "human_analyst_approval must equal APPROVED")
        add("Stage 1 unresolved issues", is_list(receipt) and _num0(dollar(receipt, "unresolved_issues")), "unresolved_issues must equal 0")
    if step_id == "framing":
        req = ["stage", "status", "analytical_question", "capacity_stance", "ai1_builder", "ai2_decision_fit_review", "ai3_framing_red_team",
               "cross_review", "framing_gate", "stakeholder_approval", "human_analyst_approval", "unresolved_issues"]
        add("Stage 2 required fields", has_fields(receipt, req), ", ".join(req))
        add("Stage 2 number", is_value(receipt, "stage", 2), "stage must equal 2")
        add("Stage 2 locked", is_value(receipt, "status", "LOCKED"), "status must equal LOCKED")
        add("Capacity stance explicit", is_list(receipt) and text_scalar(dollar(receipt, "capacity_stance")) and _s(dollar(receipt, "capacity_stance")) in ("unordered_ok", "hard_attention_budget"),
            "capacity_stance must be unordered_ok or hard_attention_budget")
        for f in ["ai1_builder", "ai2_decision_fit_review", "ai3_framing_red_team", "cross_review", "framing_gate"]:
            add(f"Stage 2 {f}", is_value(receipt, f, "PASS"), f"{f} must equal PASS")
        add("Stage 2 stakeholder approval", is_value(receipt, "stakeholder_approval", "APPROVED"), "stakeholder_approval must equal APPROVED")
        add("Stage 2 human approval", is_value(receipt, "human_analyst_approval", "APPROVED"), "human_analyst_approval must equal APPROVED")
        add("Stage 2 unresolved issues", is_list(receipt) and _num0(dollar(receipt, "unresolved_issues")), "unresolved_issues must equal 0")
    if step_id == "design":
        req = ["stage", "status", "design_version", "population", "grain", "window_start", "window_end", "decision_rules", "required_outputs",
               "ml_mode", "ai1_independent_design", "ai2_independent_design", "ai3_independent_risk_dossier", "design_exposure_disclosed",
               "cross_review", "design_gates", "human_analyst_approval", "unresolved_issues"]
        add("Stage 3 required fields", has_fields(receipt, req), ", ".join(req))
        add("Stage 3 number", is_value(receipt, "stage", 3), "stage must equal 3")
        add("Stage 3 locked", is_value(receipt, "status", "LOCKED"), "status must equal LOCKED")
        add("ML mode explicit", is_list(receipt) and text_scalar(dollar(receipt, "ml_mode")) and _s(dollar(receipt, "ml_mode")) in ("None", "A", "B"), "ml_mode must be None, A, or B")
        for f in ["ai1_independent_design", "ai2_independent_design", "ai3_independent_risk_dossier", "design_exposure_disclosed", "cross_review", "design_gates"]:
            add(f"Stage 3 {f}", is_value(receipt, f, "PASS"), f"{f} must equal PASS")
        add("Stage 3 human approval", is_value(receipt, "human_analyst_approval", "APPROVED"), "human_analyst_approval must equal APPROVED")
        add("Stage 3 unresolved issues", is_list(receipt) and _num0(dollar(receipt, "unresolved_issues")), "unresolved_issues must equal 0")
    if step_id == "execution":
        add("Stage 4 receipt present", is_list(receipt), "stage4_validation_status.json must parse")
        add("Stage 4 number", is_value(receipt, "stage", 4), "stage must equal 4")
        add("Stage 4 status", is_value(receipt, "status", "PASS"), "status must equal PASS")
    if step_id == "finish":
        req = ["stage", "status", "workflow_gate_report_sha256", "ai1_first_pass", "ai2_first_pass", "ai3_first_pass", "information_barrier",
               "cross_review", "finish_gates", "human_analyst_approval", "unresolved_issues", "deliverables"]
        add("Stage 5 required fields", has_fields(receipt, req), ", ".join(req))
        add("Stage 5 number", is_value(receipt, "stage", 5), "stage must equal 5")
        add("Stage 5 status", is_value(receipt, "status", "PASS"), "status must equal PASS")
        for f in ["ai1_first_pass", "ai2_first_pass", "ai3_first_pass", "information_barrier", "cross_review", "finish_gates"]:
            add(f"Stage 5 {f}", is_value(receipt, f, "PASS"), f"{f} must equal PASS")
        add("Human analyst approval", is_value(receipt, "human_analyst_approval", "APPROVED"), "human_analyst_approval must equal APPROVED")
        ui = dollar(receipt, "unresolved_issues") if is_list(receipt) else None
        add("Stage 5 unresolved issues", is_list(receipt) and "unresolved_issues" in (names(receipt) or []) and is_numeric(ui) and length(ui) == 1
            and values(ui)[0] is not None and values(ui)[0] == 0, "unresolved_issues must equal 0")
        dl = dollar(receipt, "deliverables") if is_list(receipt) else None
        add("Stage 5 deliverables recorded", is_list(receipt) and length(dl) > 0 and all(project_file_ok(d, root) for d in M._iter(dl)),
            "deliverables must name existing nonempty files inside the project")
        wp = paths(root)["workflow_report"]
        add("Stage 5 used certified Workflow Gate report", os.path.exists(wp) and is_list(receipt) and text_scalar(dollar(receipt, "workflow_gate_report_sha256"))
            and _s(dollar(receipt, "workflow_gate_report_sha256")).lower() == sha256_file(wp), "workflow gate report hash must match")
    if step_id == "start":
        add("Decision identity", M.m_text(dollar(receipt, "decision_id")), "Stable decision ID")
    if step_id == "framing":
        add("Question identity/type", M.m_text(dollar(receipt, "question_id")) and M.m_enum(dollar(receipt, "question_type"), ["descriptive", "associational", "predictive", "causal", "decision"]),
            "Explicit target family")
    if step_id == "design":
        checks.extend(M.m_design(receipt, M.m_read(f"{root}/artifacts/stage2_framing.json"), M.m_read(f"{root}/artifacts/stage1_decision.json"), root))
        checks.extend(M.m_ai(dollar(receipt, "ai_provenance"), M.M_STAGE_AI_ROLES["design"], root, "design"))
    if step_id == "finish":
        checks.extend(M.m_finish(M.m_read(f"{root}/artifacts/stage3_locked_design.json"), M.m_read(f"{root}/artifacts/stage4_validation_status.json"), receipt, root))
        checks.extend(M.m_ai(dollar(receipt, "ai_provenance"), M.M_STAGE_AI_ROLES["finish"], root, "finish"))
    add("Referenced evidence current", M.m_refs_ok(receipt, root, required=False), "Every declared file reference must match its hash")
    return checks


def run_workflow_gate(root):
    p = paths(root)
    import io
    import contextlib
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        status, report, _ = WG.run(p["project_root"], write=True)
        if report is not None:
            print("OVERALL:", report["result"])
    output = (buf_out.getvalue() + buf_err.getvalue()).splitlines()
    os.makedirs(os.path.dirname(p["workflow_console"]), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="execution-workflow-console-", suffix=".txt", dir=os.path.dirname(p["workflow_console"]))
    os.close(fd)
    for f in (tmp, p["workflow_console"]):
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("\n".join(output) + "\n")
    rep = read_artifact_safe(p["workflow_report"])
    passed = status == 0 and is_list(rep) and identical(dollar(rep, "result"), "PASS") and dollar(rep, "stage5_allowed") is True
    return {"passed": passed, "exit_status": status, "report": rep, "report_path": p["workflow_report"],
            "report_sha256": sha256_file(p["workflow_report"]) if os.path.exists(p["workflow_report"]) else None,
            "console_path": p["workflow_console"]}


def procedure_start(root, run_id):
    if not text_scalar(run_id):
        raise Stop("run_id must be one nonempty string")
    p = paths(root)
    if os.path.exists(p["state"]):
        raise Stop(f"Procedure run already exists: {p['state']}")
    procedure = read_procedure()
    state = {"run_id": run_id, "procedure_id": dollar(procedure, "procedure_id"), "procedure_version": dollar(procedure, "procedure_version"),
             "procedure_sha256": sha256_file(p["procedure_file"]), "status": "IN_PROGRESS", "current_step": None, "completed_steps": [],
             "framework_hashes": framework_hashes(procedure), "workflow_gate": None, "final_certificate": None,
             "started_at_utc": timestamp_utc(), "updated_at_utc": timestamp_utc()}
    save_state(state, root)
    return {"status": "STARTED", "run_id": run_id, "next_step": dollar(M._iter(dollar(procedure, "steps"))[0], "id")}


def _set(state, key, value):
    state = dict(state)
    if value is None:
        state.pop(key, None)
    else:
        state[key] = value
    return state


def procedure_begin(root, step_id):
    state = read_state(root)
    procedure = read_procedure()
    step = step_by_id(procedure, step_id)
    req = [v for v in M.unlist_values(dollar(step, "requires"))]
    checks = [
        check_result("Run is active", identical(dollar(state, "status"), "IN_PROGRESS"), "status must equal IN_PROGRESS"),
        check_result("No other step is active", dollar(state, "current_step") is None, "current_step must be null"),
        check_result("Step is not already complete", step_id not in completed_ids(state), "completed steps cannot be reopened"),
        check_result("Completed receipts unchanged", verify_completed_artifacts(state, root), "completed artifact hashes must still match"),
        check_result("Workflow Gate report unchanged", verify_workflow_report(state, root), "recorded workflow report hash must still match"),
        check_result("Released dependencies unchanged", dollar(state, "workflow_gate") is None or verify_supporting_evidence(root), "Recheck source, code, configuration, outputs and supporting reports"),
        check_result("Prerequisites complete", all(r in completed_ids(state) for r in req), "Required: " + ", ".join(as_character(RVec("chr", req)) if req else [])),
        check_result("Controlling documents unchanged", verify_framework_hashes(state), "framework hashes must match run start"),
    ]
    record = save_checks(root, step_id, "begin", checks)
    if not checks_pass(checks):
        return {"status": "BLOCKED", "step": step_id, "checks": checks}
    state = _set(state, "current_step", step_id)
    state = _set(state, "current_authorization", {"path": M.m_relative_path(record["path"], os.path.realpath(root)), "sha256": record["sha256"]})
    state["updated_at_utc"] = timestamp_utc()
    save_state(state, root)
    return {"status": "AUTHORIZED", "step": step_id, "framework": dollar(step, "framework"), "check_report": record}


def procedure_complete(root, step_id):
    state = read_state(root)
    procedure = read_procedure()
    step = step_by_id(procedure, step_id)
    r = os.path.realpath(root)
    artifact = _s(dollar(step, "artifact"))
    artifact_path = f"{r}/{artifact}"
    receipt = read_artifact_safe(artifact_path)
    checks = [
        check_result("Step was authorized", identical(dollar(state, "current_step"), step_id), "current_step must match completion request"),
        check_result("Controlling documents unchanged", verify_framework_hashes(state), "framework hashes must match run start"),
        check_result("Previously completed receipts unchanged", verify_completed_artifacts(state, root), "completed artifact hashes must still match"),
        check_result("Workflow Gate report unchanged", verify_workflow_report(state, root), "recorded workflow report hash must still match"),
        check_result("Released dependencies unchanged", dollar(state, "workflow_gate") is None or verify_supporting_evidence(root), "Recheck source, code, configuration, outputs and supporting reports"),
        check_result("Required receipt exists and parses", is_list(receipt), artifact),
    ]
    try:
        checks += validate_stage_receipt(step_id, receipt, root)
        checks += M.m_operations(root, state, step_id, receipt=artifact)
    except RError as e:
        raise Stop(str(e))
    closure = step_closure(root, step_id, receipt)
    checks.append(check_result("Stage evidence closure", closure is not None, "All receipt and packet references must remain valid before completion"))
    workflow = None
    if step_id == "execution":
        workflow = {"status": "NOT_RUN", "passed": False, "reason": "Earlier completion checks must pass before the nested Workflow Gate runs",
                    "blocked_by": [c for c in checks if c["result"] != "PASS"]}
    if step_id == "execution" and checks_pass(checks):
        workflow = run_workflow_gate(root)
        workflow["status"] = "PASS" if workflow["passed"] else "FAIL"
        checks.append(check_result("Existing Workflow Gate PASS", workflow["passed"], f"exit_status={workflow['exit_status']}; report={workflow['report_path']}"))
    record = save_checks(root, step_id, "complete", checks, {"workflow_gate": workflow})
    if not checks_pass(checks):
        return {"status": "FAIL", "step": step_id, "checks": checks, "workflow_gate": workflow}
    ops = f"artifacts/operations/{step_id}.json"
    cs = dollar(state, "completed_steps")
    cs = dict(cs) if isinstance(cs, dict) else {}
    cs[step_id] = {"completed_at_utc": timestamp_utc(), "artifact": {"path": artifact, "sha256": sha256_file(artifact_path)},
                   "supporting_files": M.m_refs(receipt) + [{"path": ops, "sha256": sha256_file(f"{r}/{ops}")}],
                   "evidence_closure": closure, "authorization": dollar(state, "current_authorization"),
                   "check_report": {"path": record["path"], "sha256": record["sha256"]}}
    if cs[step_id]["authorization"] is None:
        del cs[step_id]["authorization"]
    state = dict(state)
    state["completed_steps"] = cs
    if step_id == "execution":
        state["workflow_gate"] = {"status": "PASS", "report_path": "artifacts/workflow_gate_status.json", "report_sha256": workflow["report_sha256"],
                                  "console_path": "artifacts/procedure/checks/execution-workflow-gate-console.txt", "verified_at_utc": timestamp_utc()}
    if step_id == "finish":
        cs[step_id]["deliverables"] = [{"path": d, "sha256": sha256_file(f"{root}/{_s(d)}")} for d in M._iter(dollar(receipt, "deliverables"))]
    state = _set(state, "current_step", None)
    state["updated_at_utc"] = timestamp_utc()
    save_state(state, root)
    ids = [_s(dollar(s, "id")) for s in M._iter(dollar(procedure, "steps"))]
    pos = ids.index(step_id)
    return {"status": "PASS", "completed_step": step_id, "next_step": ids[pos + 1] if pos < len(ids) - 1 else "FINALIZE", "check_report": record}


def procedure_amend(root, step_id, new_receipt_path, change_record_path):
    state = read_state(root)
    procedure = read_procedure()
    step = step_by_id(procedure, step_id)
    r = os.path.realpath(root)
    ids = [_s(dollar(s, "id")) for s in M._iter(dollar(procedure, "steps"))]
    later = ids[ids.index(step_id) + 1:]
    history = M._iter(nz(dollar(state, "amendment_history"), []))
    recorded = nz(M.D(elt(dollar(state, "completed_steps"), step_id), "artifact", "sha256"), "")
    recorded_s = _s(recorded) or ""
    receipt_ok = project_file_ok(new_receipt_path, r)
    receipt = read_artifact_safe(f"{r}/{new_receipt_path}") if receipt_ok else None
    new_sha = sha256_file(f"{r}/{new_receipt_path}") if receipt_ok else ""
    change = read_artifact_safe(f"{r}/{change_record_path}") if project_file_ok(change_record_path, r) else None
    req = ["change_id", "step", "reason", "approval_text", "approval_timestamp", "superseded_sha256", "new_sha256", "archive_path"]
    fields_ok = has_fields(change, req) and all(text_scalar(elt(change, f)) for f in req)
    change_id = _s(dollar(change, "change_id")) if fields_ok else ""
    id_ok = bool(re.search(r"^[A-Za-z0-9._-]+$", change_id)) and change_id not in [nz(_s(dollar(e, "change_id")), "") for e in history]
    approval_ok = (fields_ok and not re.search(r"^\s*(PENDING|TBD|TODO)\b", _s(dollar(change, "approval_text")), re.IGNORECASE)
                   and bool(re.search(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?(Z|[+-][0-9]{2}:[0-9]{2})$", _s(dollar(change, "approval_timestamp")))))
    archive_path = _s(dollar(change, "archive_path")) if fields_ok else ""
    archive_file = f"{r}/{archive_path}"
    protected = [artifact for artifact in [_s(dollar(step, "artifact")), new_receipt_path, change_record_path]]
    protected += [nz(_s(M.D(v, "artifact", "path")), "") for v in M._iter(nz(dollar(state, "completed_steps"), []))]
    protected += [nz(_s(M.D(e, "superseded", "path")), "") for e in history]
    archive_ok = (project_path_ok(archive_path) and not os.path.isdir(archive_file) and
                  resolve_project_path(archive_path, r) not in [resolve_project_path(p, r) for p in protected] and
                  (not os.path.exists(archive_file) or sha256_file(archive_file) == recorded_s.lower()))
    checks = [
        check_result("Run is active", identical(dollar(state, "status"), "IN_PROGRESS"), "status must equal IN_PROGRESS"),
        check_result("Step is complete", step_id in completed_ids(state), "only a completed step can be amended; completed steps are never reopened"),
        check_result("No later step is complete", not any(i in completed_ids(state) for i in later), "Later steps: " + ", ".join(later)),
        check_result("Step has no nested completion gate", dollar(step, "completion_gate") is None, "a step completed by a nested gate cannot be amended; its gate result would go stale"),
        check_result("Controlling documents unchanged", verify_framework_hashes(state), "framework hashes must match run start"),
        check_result("Completed receipts unchanged", verify_completed_artifacts(state, root), "completed artifact hashes must still match"),
        check_result("Workflow Gate report unchanged", verify_workflow_report(state, root), "recorded workflow report hash must still match"),
        check_result("Released dependencies unchanged", dollar(state, "workflow_gate") is None or verify_supporting_evidence(root), "Recheck source, code, configuration, outputs and supporting reports"),
        check_result("Change record exists and parses", is_list(change), change_record_path),
        check_result("Change record required fields", fields_ok, ", ".join(req)),
        check_result("Change identifier valid and unused", id_ok, "change_id uses letters, digits, '.', '_' or '-' and is not already in amendment_history"),
        check_result("Change record names this step", is_value(change, "step", step_id), "step must equal the amended step"),
        check_result("Owner approval recorded", approval_ok, "approval_text must be explicit (not PENDING/TBD/TODO); approval_timestamp must be ISO 8601 with Z or a UTC offset"),
        check_result("Superseded hash matches recorded receipt", text_scalar(recorded) and is_value(change, "superseded_sha256", recorded_s.lower()), "superseded_sha256 must equal the completed step's recorded artifact sha256"),
        check_result("New receipt exists and parses", is_list(receipt), new_receipt_path),
        check_result("New hash matches new receipt", receipt_ok and is_value(change, "new_sha256", new_sha) and new_sha != recorded_s.lower(), "new_sha256 must equal the new receipt's sha256 and differ from the superseded receipt"),
        check_result("New receipt names what it supersedes", text_scalar(recorded) and is_value(receipt, "supersedes_sha256", recorded_s.lower()), "supersedes_sha256 must equal the superseded sha256"),
        check_result("Archive path is safe", archive_ok, "archive_path must be a new project-relative file (or already hold the superseded bytes), distinct from live receipts"),
    ]
    try:
        checks += validate_stage_receipt(step_id, receipt, root) + M.m_change(change)
    except RError as e:
        raise Stop(str(e))
    closure = step_closure(root, step_id, receipt)
    art = _s(dollar(step, "artifact"))
    checks.append(check_result("Amendment preserves referenced history",
                               closure is not None and not any(identical(dollar(x, "path"), art) and not identical(dollar(x, "sha256"), new_sha) for x in closure),
                               "Do not overwrite a candidate referenced by a past packet; use immutable versions or a successor"))
    record = save_checks(root, step_id, f"amend-{change_id}" if id_ok else "amend", checks)
    if not checks_pass(checks):
        return {"status": "FAIL", "step": step_id, "checks": checks}
    artifact_path = f"{r}/{art}"
    os.makedirs(os.path.dirname(archive_file), exist_ok=True)
    if not os.path.exists(archive_file):
        shutil.copyfile(artifact_path, archive_file)
    if sha256_file(archive_file) != recorded_s.lower():
        raise Stop("Archived receipt does not match superseded_sha256")
    tmp = artifact_path + ".amend.tmp"
    shutil.copyfile(f"{r}/{new_receipt_path}", tmp)
    if sha256_file(tmp) != new_sha:
        raise Stop("Could not stage the new receipt")
    os.replace(tmp, artifact_path)
    if sha256_file(artifact_path) != new_sha:
        raise Stop(f"Could not install the new receipt: {art}")
    entry = {"change_id": change_id, "step": step_id, "amended_at_utc": timestamp_utc(), "approval_timestamp": dollar(change, "approval_timestamp"),
             "superseded": {"path": archive_path.replace("\\", "/"), "sha256": recorded_s.lower()},
             "new": {"path": art, "sha256": new_sha, "source_path": new_receipt_path.replace("\\", "/")},
             "change_record": {"path": change_record_path.replace("\\", "/"), "sha256": sha256_file(f"{r}/{change_record_path}")},
             "check_report": {"path": record["path"], "sha256": record["sha256"]}}
    state = dict(state)
    state["amendment_history"] = list(history) + [entry]
    cs = dict(dollar(state, "completed_steps"))
    cur = dict(cs[step_id])
    ops = f"artifacts/operations/{step_id}.json"
    cur["supporting_files"] = M.m_refs(receipt) + [{"path": ops, "sha256": sha256_file(f"{root}/{ops}")}]
    cur["evidence_closure"] = closure
    cur["artifact"] = dict(dollar(cur, "artifact"))
    cur["artifact"]["sha256"] = new_sha
    cs[step_id] = cur
    state["completed_steps"] = cs
    state["updated_at_utc"] = timestamp_utc()
    save_state(state, root)
    return {"status": "AMENDED", "step": step_id, "change_id": change_id, "superseded_sha256": recorded_s.lower(), "new_sha256": new_sha,
            "archive_path": entry["superseded"]["path"], "check_report": record}


def procedure_status(root):
    state = read_state(root)
    procedure = read_procedure()
    ids = [_s(dollar(s, "id")) for s in M._iter(dollar(procedure, "steps"))]
    done = completed_ids(state)
    if dollar(state, "current_step") is not None:
        nxt = dollar(state, "current_step")
    else:
        rem = [i for i in ids if i not in done]
        nxt = rem[0] if rem else "FINALIZE"
    out = {"run_id": dollar(state, "run_id"), "status": dollar(state, "status"), "current_step": dollar(state, "current_step"),
           "completed_steps": done, "next_step": nxt, "workflow_gate": dollar(state, "workflow_gate"), "final_certificate": dollar(state, "final_certificate")}
    if length(nz(dollar(state, "amendment_history"), [])) > 0:
        out["amendment_history"] = dollar(state, "amendment_history")
    return out


def procedure_finalize(root):
    state = read_state(root)
    procedure = read_procedure()
    p = paths(root)
    required = [_s(dollar(s, "id")) for s in M._iter(dollar(procedure, "steps"))]
    wg = dollar(state, "workflow_gate")
    cs = dollar(state, "completed_steps")
    checks = [
        check_result("No step is active", dollar(state, "current_step") is None, "current_step must be null"),
        check_result("All five stages complete", all(i in completed_ids(state) for i in required), ", ".join(required)),
        check_result("Workflow Gate certified Execution", is_list(wg) and identical(dollar(wg, "status"), "PASS"), "workflow_gate status must equal PASS"),
        check_result("Completed receipts unchanged", verify_completed_artifacts(state, root), "completed artifact hashes must still match"),
        check_result("Workflow Gate report unchanged", verify_workflow_report(state, root), "recorded workflow report hash must still match"),
        check_result("Released dependencies unchanged", wg is None or verify_supporting_evidence(root), "Recheck source, code, configuration, outputs and supporting reports"),
        check_result("Supporting evidence unchanged", verify_supporting_evidence(root), "evidence files must match the released Workflow Gate report"),
        check_result("Stage 5 deliverables unchanged", verify_file_manifest(M.D(cs, "finish", "deliverables") if is_list(cs) else None, root), "deliverables must match their Finish completion hashes"),
        check_result("Controlling documents unchanged", verify_framework_hashes(state), "framework hashes must match run start"),
    ]
    for st in M._iter(dollar(procedure, "steps")):
        checks += M.m_operations(root, state, _s(dollar(st, "id")), final=True, receipt=dollar(st, "artifact"))
    try:
        refs = M.m_refs(cs) + [{"path": "artifacts/workflow_gate_status.json", "sha256": dollar(wg, "report_sha256")}]
        inventory = M.m_inventory(refs, root, closure_resolutions(root, required) + closure_hist(root, required))
    except RError:
        inventory = None
    checks.append(check_result("Evidence dependency closure", inventory is not None, "All referenced files must exist at authoritative root with matching hashes"))
    record = save_checks(root, "final", "certification", checks)
    if not checks_pass(checks):
        if os.path.exists(p["certificate"]):
            arch = f"{p['project_root']}/artifacts/procedure/certificates"
            os.makedirs(arch, exist_ok=True)
            shutil.copyfile(p["certificate"], f"{arch}/{sha256_file(p['certificate'])}.json")
        write_json_atomic({"result": "FAIL", "certified": False, "run_id": dollar(state, "run_id"), "checks": checks, "checked_at_utc": timestamp_utc()}, p["certificate"])
        state = dict(state)
        state["status"] = "IN_PROGRESS"
        state["final_certificate"] = {"path": "artifacts/final_certificate.json", "sha256": sha256_file(p["certificate"])}
        state["updated_at_utc"] = timestamp_utc()
        save_state(state, root)
        return {"status": "FAIL", "checks": checks}
    completed = [{"id": i, "artifact_path": M.D(elt(cs, i), "artifact", "path"), "artifact_sha256": M.D(elt(cs, i), "artifact", "sha256")} for i in required]
    cert = {"certificate": "five_stage_procedure_certificate", "result": "PASS", "certified": True, "run_id": dollar(state, "run_id"),
            "procedure_id": dollar(state, "procedure_id"), "procedure_version": dollar(state, "procedure_version"),
            "procedure_sha256": dollar(state, "procedure_sha256"), "completed_steps": completed, "deliverables": M.D(cs, "finish", "deliverables"),
            "workflow_gate_report_sha256": dollar(wg, "report_sha256"), "certification_check_sha256": record["sha256"], "certified_at_utc": timestamp_utc()}
    if length(nz(dollar(state, "amendment_history"), [])) > 0:
        cert["amendment_history"] = dollar(state, "amendment_history")
    if dollar(state, "predecessor") is not None:
        cert["predecessor"] = dollar(state, "predecessor")
    s5 = read_artifact_safe(f"{root}/artifacts/stage5_interpretation_status.json")
    assurance = dict(dollar(s5, "assurance") or {}) if isinstance(dollar(s5, "assurance"), dict) or dollar(s5, "assurance") is None else {}
    inv_path = f"artifacts/procedure/{os.path.basename(record['path'])}-inventory.json"
    write_json_atomic(inventory, f"{root}/{inv_path}")
    cert["evidence_inventory"] = {"path": inv_path, "sha256": sha256_file(f"{root}/{inv_path}")}
    assurance.update({"procedure": "recorded_checks_passed", "process_order": "recorded_order_verified",
                      "manual_send_prevention": "not_demonstrated", "deviations": "see_frozen_stage_operations"})
    cert["assurance"] = assurance
    cert["assurance_note"] = "Recorded checks and attestations; not a proof of scientific truth, AI independence, or profitable action."
    cert["framework_hashes"] = dollar(state, "framework_hashes")
    # R uses digest::digest(<R object>); the port hashes canonical JSON instead (recorded as such).
    cert["certificate_sha256"] = hashlib.sha256(json.dumps(WG.to_json(cert), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    cert["certificate_sha256_method"] = "sha256 of canonical JSON (python port)"
    write_json_atomic(cert, p["certificate"])
    state = dict(state)
    state["status"] = "CERTIFIED"
    state["final_certificate"] = {"path": "artifacts/final_certificate.json", "sha256": sha256_file(p["certificate"])}
    state["updated_at_utc"] = timestamp_utc()
    save_state(state, root)
    return cert


def procedure_successor(root, predecessor_root, run_id, change_record_path):
    if os.path.realpath(root) == os.path.realpath(predecessor_root):
        raise Stop("Successor needs a separate project root")
    old = read_state(predecessor_root)
    if not project_file_ok(change_record_path, root):
        raise Stop("Successor change record must be a nonempty file inside the new project")
    change = read_artifact_safe(f"{root}/{change_record_path}")
    checks = M.m_change(change)
    if not checks_pass(checks) or not M.m_text(dollar(change, "approval_text")) or not M.m_text(dollar(change, "approval_timestamp")):
        raise Stop("Successor requires classified change, exposure, invalidation and explicit owner approval")
    if os.path.exists(paths(root)["state"]):
        raise Stop("Successor already exists")
    old_path = paths(predecessor_root)["state"]
    d = f"{root}/artifacts/predecessor"
    os.makedirs(d, exist_ok=True)
    arch = f"{d}/run_state.json"
    if os.path.exists(arch):
        raise Stop("Could not preserve predecessor state")
    shutil.copyfile(old_path, arch)
    cert = paths(predecessor_root)["certificate"]
    cref = None
    if os.path.exists(cert):
        tgt = f"{d}/final_certificate.json"
        if os.path.exists(tgt):
            raise Stop("Could not preserve predecessor certificate")
        shutil.copyfile(cert, tgt)
        cref = {"path": "artifacts/predecessor/final_certificate.json", "sha256": sha256_file(tgt)}
    result = procedure_start(root, run_id)
    state = dict(read_state(root))
    state["predecessor"] = {"run_id": dollar(old, "run_id"), "state": {"path": "artifacts/predecessor/run_state.json", "sha256": sha256_file(arch)},
                            "change_record": {"path": change_record_path, "sha256": sha256_file(f"{root}/{change_record_path}")}}
    if cref is not None:
        state["predecessor"]["certificate"] = cref
    save_state(state, root)
    return result


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) < 2:
            raise Stop("Usage: python3 -m gates.procedure start|begin|complete|status|finalize|amend|successor <project-root> ...")
        action, root = args[0], args[1]
        if action == "start":
            if len(args) < 3:
                raise Stop("start requires <run-id>")
            result = procedure_start(root, args[2])
        elif action == "begin":
            if len(args) < 3:
                raise Stop("begin requires <step>")
            result = procedure_begin(root, args[2])
        elif action == "complete":
            if len(args) < 3:
                raise Stop("complete requires <step>")
            result = procedure_complete(root, args[2])
        elif action == "status":
            result = procedure_status(root)
        elif action == "successor":
            if len(args) < 5:
                raise Stop("successor requires <new-project-root> <predecessor-root> <new-run-id> <change-record>")
            result = procedure_successor(root, args[2], args[3], args[4])
        elif action == "finalize":
            result = procedure_finalize(root)
        elif action == "amend":
            if len(args) < 5:
                raise Stop("amend requires <completed-step> <new-receipt> <change-record>")
            result = procedure_amend(root, args[2], args[3], args[4])
        else:
            raise Stop(f"Unknown action: {action}")
    except (Stop, RError) as e:
        sys.stderr.write(f"Error: {e}\nExecution halted\n")
        return 1
    print(json.dumps(WG.to_json(result), indent=2, ensure_ascii=False))
    if isinstance(result, dict) and result.get("status") in ("FAIL", "BLOCKED"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
