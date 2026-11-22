"""G0 packet integrity (docs/gates.md, docs/handoff.md).

Input: artifacts/packets/index.json
  {"packets": [{"id", "path", "status": "draft"|"sent"|"captured"|"answered", "sha256" (required once sent),
                "reply": {"path", "sha256"} (required once captured or answered)}],
   "forbidden_strings": [text that must never appear in a packet, e.g. a private folder name] (optional),
   "forbidden_path_prefixes": [project-relative prefixes no input may come from] (optional; "private/" always applies)}

Checks every packet in the index:
- the packet file is a safe project path, non-empty, and (once sent) still has its sealed hash;
- every header field of the handoff format is present, PACKET_ID equals the index id, STAGE and ROLE are known;
- every INPUTS line names a whole current file: `- <path> sha256=<hash> bytes=<n>` with the current hash and size;
  split inputs list every part `part k of K`;
- no input comes from a forbidden prefix and no input is an answer-key file; NOT ALLOWED TO SEE names the answer key;
- no leftover template text: `TEMPLATE`, `{{placeholder}}`, `<angle placeholder>` from the format, or a field
  value that starts with PENDING/TBD/TODO; no forbidden string;
- REPLY ENDS WITH requires `ANSWERED <PACKET_ID>` and a list of produced files;
- a correction `-vN` (N >= 2) names the packet it SUPERSEDES, which must be in the index;
- an answered packet has a sealed reply whose produced-files list is not blank, lists every EXPECTED OUTPUT path,
  names only existing files, and whose last non-empty line is `ANSWERED <PACKET_ID>`. A file that appears on disk
  is not a completed send: without that reply the packet stays unanswered (reported in `unanswered`; G6 refuses it).
- a packet may be marked superseded in the index (`superseded_by`, `superseded_reason`, `superseded_at`): the newer packet
  must be in the index, the reason must be real text and the time an ISO timestamp. A superseded packet keeps its
  sealed hash (history is never rewritten) but its content and reply checks are not applied, it is not counted as
  unanswered, and it is reported in `superseded`, so a replaced packet no longer blocks G6;
- no input is a JSON file holding template placeholder references (all-zero or NOT_SET hashes, or a template
  `*.example.json`): R `finalize` walks every referenced JSON file and would fail on them (gates/guards.py);
- every `MISSING INPUT: <item>` line in a sealed reply was checked against the public files (gates/derivability.py).

Captured replies (case02 change A4): a tool that saves a child's reply records the packet as "captured", never straight
as "answered". G0 runs every reply and derivability check on a captured packet but still lists it as unanswered (and in
`captured`), so G6 and a stage close refuse it. Only `python3 -m gates.packet promote <root> <packet id>` moves it to
"answered", and only when G0 passes; on a FAIL the packet stays captured and the command exits 1.
"""
from __future__ import annotations

import os
import re

from gates import guards
from gates.common import GATE_DIR, Gate, PLACEHOLDER_RE, TIMESTAMP_RE, load_json_strict, ref_current, safe_rel, sha256_file, text
from gates.derivability import derivability_checks, raised_in_replies

INDEX = "artifacts/packets/index.json"
FIELDS = ["PACKET_ID", "ROLE", "STAGE", "TASK", "INPUTS", "ALLOWED TO SEE", "NOT ALLOWED TO SEE", "RULES",
          "EXPECTED OUTPUT", "REPLY ENDS WITH"]
OPTIONAL = ["SUPERSEDES"]
STAGES = {"1", "2", "2F", "3", "4", "5"}
ROLES = {"lead-designer", "second-designer", "risk-reviewer", "sql-analyst", "analyst-r-a", "analyst-r-b"}
DEFAULT_FORBIDDEN_PREFIXES = ["private/"]
STATUSES = ("draft", "sent", "captured", "answered")

FIELD_RE = re.compile(r"^(" + "|".join(re.escape(f) for f in sorted(FIELDS + OPTIONAL, key=len, reverse=True)) + r"):[ \t]*(.*)$")
INPUT_RE = re.compile(r"^\s*-\s+(?P<path>\S+)\s+sha256=(?P<sha>[0-9A-Fa-f]{64})\s+bytes=(?P<bytes>[0-9]+)"
                      r"(?:\s+part\s+(?P<k>[0-9]+)\s+of\s+(?P<K>[0-9]+))?\s*$")
LIST_RE = re.compile(r"^\s*-\s+(\S+)\s*$")
TEMPLATE_RES = [(re.compile(r"\bTEMPLATE\b"), "TEMPLATE marker"),
                (re.compile(r"\{\{[^{}]*\}\}"), "{{placeholder}}"),
                (re.compile(r"<(?:run|stage|seq|child role|one paragraph|relative path|hash|n|list|others|"
                            r"named output paths[^>]*|only the rules[^>]*|1-5 or 2F)>"), "<format placeholder>")]
VERSION_RE = re.compile(r"-v([0-9]+)$")
ANSWER_KEY_NAME = re.compile(r"answer[_ -]?key", re.IGNORECASE)


def _norm_role(r):
    return re.sub(r"[\s_]+", "-", r.strip().lower())


def parse_packet(body):
    """Returns {field: [lines]} for the handoff format; the first line of a field is its inline value."""
    out, cur = {}, None
    for line in body.splitlines():
        m = FIELD_RE.match(line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            if m.group(2).strip():
                out[cur].append(m.group(2).strip())
        elif cur is not None and line.strip():
            out[cur].append(line.rstrip())
    return out


def _list_paths(lines):
    return [m.group(1) for m in (LIST_RE.match(x) for x in lines) if m]


def parse_reply(body):
    """Produced-files list: lines `- <path>` after a `PRODUCED FILES:` line, up to the next blank line or the end."""
    lines = body.splitlines()
    start = next((i for i, x in enumerate(lines) if x.strip().upper().rstrip(":") == "PRODUCED FILES"), None)
    produced = []
    if start is not None:
        for x in lines[start + 1:]:
            m = LIST_RE.match(x)
            if not m:
                break
            produced.append(m.group(1))
    last = next((x.strip() for x in reversed(lines) if x.strip()), "")
    return start is not None, produced, last


def _read(full):
    with open(full, "rb") as fh:
        return fh.read().decode("utf-8")


def g0(root):
    g = Gate("G0", root)
    idx = g.load(INDEX, "Packet index") or {}
    pk = idx.get("packets")
    pk = pk if isinstance(pk, list) else []
    g.add("Packets listed", bool(pk) and all(isinstance(p, dict) for p in pk), "packets: non-empty list of objects")
    ids = [p.get("id") for p in pk if isinstance(p, dict)]
    g.add("Packet ids unique", all(text(i) for i in ids) and len(set(ids)) == len(ids), f"ids {ids}")
    fs = idx.get("forbidden_strings", [])
    fs = [s for s in fs if text(s)] if isinstance(fs, list) else []
    fp = idx.get("forbidden_path_prefixes", [])
    fp = DEFAULT_FORBIDDEN_PREFIXES + ([s for s in fp if text(s)] if isinstance(fp, list) else [])
    unanswered, superseded, captured = [], [], []
    by_id = {p.get("id"): p for p in pk if isinstance(p, dict)}
    for p in pk:
        if not isinstance(p, dict):
            continue
        if _is_superseded(p):
            _check_superseded(g, root, p, by_id)
            superseded.append(p.get("id"))
            continue
        _check_packet(g, root, p, set(ids), fs, fp)
        if p.get("status") != "answered":
            unanswered.append(p.get("id"))
        if p.get("status") == "captured":
            captured.append(p.get("id"))
    derivability_checks(g, root, raised_in_replies(root, [p for p in pk if isinstance(p, dict)]), forbidden_prefixes=tuple(fp),
                        prefix="Derivability: ")
    g.extra["unanswered"] = unanswered
    g.extra["superseded"] = superseded
    g.extra["captured"] = captured
    return g.result()


SUPERSEDE_KEYS = ("superseded_by", "superseded_reason", "superseded_at")


def _is_superseded(p):
    return any(k in p for k in SUPERSEDE_KEYS)


def _check_superseded(g, root, p, by_id):
    """A superseded packet: sealed hash still current; a valid pointer to a newer packet, a reason and a timestamp."""
    pid = p.get("id")
    lab = f"Packet {pid}"
    new = p.get("superseded_by")
    chain, cur = [pid], new
    while cur in by_id and cur not in chain and _is_superseded(by_id[cur]):
        chain.append(cur)
        cur = by_id[cur].get("superseded_by")
    g.add(f"{lab} superseded by a packet in the index", text(new) and new != pid and new in by_id and cur in by_id and cur not in chain,
          f"superseded_by must name another packet in the index (no cycle); got {new!r}")
    reason = p.get("superseded_reason")
    g.add(f"{lab} supersession reason", text(reason) and not PLACEHOLDER_RE.search(reason), "superseded_reason: why it was replaced")
    at = p.get("superseded_at")
    g.add(f"{lab} supersession time", isinstance(at, str) and TIMESTAMP_RE.match(at) is not None,
          "superseded_at: ISO timestamp with zone, e.g. 2026-11-10T18:10:59-06:00")
    rel = p.get("path")
    full = safe_rel(root, rel) if text(rel) else None
    if p.get("status") in ("sent", "captured", "answered"):
        ok = full is not None and os.path.isfile(full) and ref_current(root, {"path": rel, "sha256": p.get("sha256")})
        g.add(f"{lab} sealed hash current (superseded)", ok, "a superseded packet that was sent stays sealed: history is kept, not rewritten")
        if ok:
            g.use(rel)


def _check_packet(g, root, p, all_ids, forbidden_strings, forbidden_prefixes):
    pid = p.get("id")
    lab = f"Packet {pid}"
    status = p.get("status")
    g.add(f"{lab} status", status in STATUSES, f"status in {STATUSES}")
    rel = p.get("path")
    full = safe_rel(root, rel) if text(rel) else None
    if full is None or not os.path.isfile(full) or os.path.getsize(full) == 0:
        g.add(f"{lab} file present", False, f"{rel!r}: safe, existing, non-empty project path required")
        return
    g.use(rel)
    if status in ("sent", "captured", "answered"):
        g.add(f"{lab} sealed hash current", ref_current(root, {"path": rel, "sha256": p.get("sha256")}),
              "a sent packet is sealed: its recorded sha256 must equal the current bytes")
    try:
        body = _read(full)
    except UnicodeDecodeError:
        g.add(f"{lab} is UTF-8 text", False, rel)
        return
    f = parse_packet(body)
    missing = [k for k in FIELDS if not f.get(k)]
    g.add(f"{lab} header fields", not missing, f"missing or empty: {missing}" if missing else "all present")
    g.add(f"{lab} PACKET_ID matches index", (f.get("PACKET_ID") or [""])[0].strip() == pid, f"PACKET_ID must equal {pid!r}")
    g.add(f"{lab} STAGE known", (f.get("STAGE") or [""])[0].strip().upper() in STAGES, f"STAGE in {sorted(STAGES)}")
    g.add(f"{lab} ROLE known", _norm_role((f.get("ROLE") or [""])[0]) in ROLES, f"ROLE in {sorted(ROLES)}")
    # inputs: whole, current, safe, not forbidden
    in_lines = f.get("INPUTS") or []
    bad_lines, stale, forbidden, parts = [], [], [], {}
    for line in in_lines:
        m = INPUT_RE.match(line)
        if not m:
            bad_lines.append(line.strip())
            continue
        ip, isha, nb = m.group("path"), m.group("sha").lower(), int(m.group("bytes"))
        ifull = safe_rel(root, ip)
        if any(ip.startswith(x) for x in forbidden_prefixes) or ANSWER_KEY_NAME.search(ip):
            forbidden.append(ip)
        if ifull is None or not os.path.isfile(ifull) or os.path.getsize(ifull) != nb or sha256_file(ifull) != isha:
            stale.append(ip)
        else:
            g.use(ip)
        if m.group("k"):
            parts.setdefault((os.path.dirname(ip), int(m.group("K"))), set()).add(int(m.group("k")))
    g.add(f"{lab} inputs listed", bool(in_lines) and not bad_lines,
          "each line `- <path> sha256=<hash> bytes=<n>` [part k of K]" + (f"; malformed: {bad_lines}" if bad_lines else ""))
    g.add(f"{lab} inputs whole and current", not stale and bool(in_lines),
          "every input at the named path with the named hash and byte count" + (f"; not current: {stale}" if stale else ""))
    incomplete = [f"{d or '.'}: parts {sorted(ks)} of {K}" for (d, K), ks in parts.items() if ks != set(range(1, K + 1))]
    g.add(f"{lab} split inputs complete", not incomplete, f"missing parts: {incomplete}" if incomplete else "ok")
    g.add(f"{lab} no forbidden inputs", not forbidden, f"forbidden: {forbidden}" if forbidden else f"prefixes {forbidden_prefixes}")
    if (f.get("STAGE") or [""])[0].strip().upper() == "5" and _norm_role((f.get("ROLE") or [""])[0]) in ("second-designer", "risk-reviewer"):
        ips = {m.group("path"): m.group("sha").lower() for m in (INPUT_RE.match(x) for x in in_lines) if m}
        precheck_checks(g, root, lab, ips)
    tph = guards.placeholder_refs(root, [m.group("path") for m in (INPUT_RE.match(x) for x in in_lines) if m])
    g.add(f"{lab} no template placeholder references", not tph,
          (guards.describe(tph) + " -- " + guards.TEMPLATE_HINT) if tph else "none")
    nats = " ".join(f.get("NOT ALLOWED TO SEE") or [])
    g.add(f"{lab} answer key withheld", ANSWER_KEY_NAME.search(nats) is not None, "NOT ALLOWED TO SEE must name the answer key")
    # leftover template / forbidden content
    hits = sorted({lab_ for rx, lab_ in TEMPLATE_RES if rx.search(body)})
    ph = [k for k, v in f.items() if v and PLACEHOLDER_RE.search(v[0])]
    g.add(f"{lab} no template leftovers", not hits and not ph,
          (f"found {hits}" if hits else "") + (f"; placeholder values in {ph}" if ph else "") or "none")
    fhits = [s for s in forbidden_strings if s in body]
    g.add(f"{lab} no forbidden strings", not fhits, f"{len(fhits)} forbidden string(s) present" if fhits else "none")
    # reply contract
    rew = " ".join(f.get("REPLY ENDS WITH") or [])
    g.add(f"{lab} reply contract", f"ANSWERED {pid}" in rew and "produced files" in rew.lower(),
          f"REPLY ENDS WITH must require `ANSWERED {pid}` and a list of produced files")
    expected = _list_paths(f.get("EXPECTED OUTPUT") or [])
    g.add(f"{lab} expected outputs named", bool(expected) and all(safe_rel(root, x) for x in expected),
          "EXPECTED OUTPUT: one `- <project path>` line per output")
    vm = VERSION_RE.search(pid or "")
    if vm and int(vm.group(1)) >= 2:
        sup = (f.get("SUPERSEDES") or [""])[0].strip()
        g.add(f"{lab} names what it supersedes", text(sup) and sup in all_ids and sup != pid, "SUPERSEDES: <earlier packet id in the index>")
    if status in ("captured", "answered"):
        _check_reply(g, root, p, pid, lab, expected)


G5P_HISTORY_PREFIX = "G5P-"


def _runner_written(root, sha):
    """True when these bytes are a write-once history copy the gate runner wrote (artifacts/gates/history/G5P-*.json)."""
    hist = os.path.join(root, GATE_DIR, "history")
    try:
        names = [n for n in os.listdir(hist) if n.startswith(G5P_HISTORY_PREFIX) and n.endswith(".json")]
    except OSError:
        return False
    return any(sha256_file(os.path.join(hist, n)) == sha for n in names)


def precheck_checks(g, root, lab, inputs):
    """Known fix 3 (owner correction 2026-11-20): a file name is not a precheck. A Stage 5 review packet must carry, as an
    input, a G5P gate record written by the gate runner (its bytes equal a write-once copy under artifacts/gates/history/)
    whose result is PASS and whose `ledger` {path, sha256} is the exact claims ledger listed in the same packet, at the same
    path and hash. Every input that G5P recorded must still be unchanged, and so must every deliverable and companion it
    recorded under `deliverables` (repair round 1). `inputs` maps packet input paths to their hashes."""
    recs = []
    for path, sha in inputs.items():
        if not path.lower().endswith(".json"):
            continue
        full = safe_rel(root, path)
        obj, err = load_json_strict(full) if full else (None, "unsafe")
        if not err and isinstance(obj, dict) and obj.get("gate") == "G5P":
            recs.append((path, sha, obj))
    g.add(f"{lab} Stage 5 review carries a precheck log", bool(recs),
          "a Stage 5 review packet lists the G5P gate record (artifacts/gates/history/G5P-*.json) of the ledger it reviews "
          "as an input (case02 change 2); a file merely named 'precheck' does not count")
    good, why = [], []
    for path, sha, rec in recs:
        led = rec.get("ledger") if isinstance(rec.get("ledger"), dict) else {}
        lpath, lsha = led.get("path"), str(led.get("sha256") or "").lower()
        stale = [i.get("path") for i in rec.get("inputs", []) if not (isinstance(i, dict) and ref_current(root, i, need_nonempty=False))] \
            if isinstance(rec.get("inputs"), list) else ["(no inputs)"]
        problems = []
        if rec.get("result") != "PASS":
            problems.append(f"result {rec.get('result')!r}")
        if not _runner_written(root, sha):
            problems.append("not a gate-runner record (no matching artifacts/gates/history/G5P-*.json)")
        if not (text(lpath) and lsha and inputs.get(lpath) == lsha):
            problems.append(f"its ledger {lpath!r} at {lsha[:12] or None} is not an input of this packet at that hash")
        dl = rec.get("deliverables")
        if not (isinstance(dl, list) and dl and all(isinstance(d, dict) for d in dl)):
            problems.append("it records no reviewed deliverables (repair round 1: G5P binds every report it reviewed)")
        else:
            changed = [d.get("path") for d in dl if not ref_current(root, d, need_nonempty=False)]
            moved = [d.get("path") for d in dl if d.get("path") in inputs and inputs[d.get("path")] != str(d.get("sha256") or "").lower()]
            if changed or moved:
                problems.append(f"reports changed since G5P ran: {sorted(set(changed + moved))[:4]}")
        if stale:
            problems.append(f"inputs changed since G5P ran: {stale[:4]}")
        (why.append(f"{path}: " + "; ".join(problems)) if problems else good.append(path))
    g.add(f"{lab} Stage 5 precheck PASS for the exact ledger", bool(good),
          "G5P PASS recorded for the claims ledger in this packet (same path and sha256), inputs unchanged"
          + (f"; {why[:3]}" if why and not good else ""))


def _check_reply(g, root, p, pid, lab, expected):
    r = p.get("reply")
    ok = ref_current(root, r)
    g.add(f"{lab} reply sealed", ok, "reply {path, sha256} current (captured and sealed by the parent)")
    if not ok:
        return
    g.use(r["path"])
    try:
        body = _read(safe_rel(root, r["path"]))
    except UnicodeDecodeError:
        g.add(f"{lab} reply is UTF-8 text", False, r["path"])
        return
    has_list, produced, last = parse_reply(body)
    g.add(f"{lab} reply ends with ANSWERED", last == f"ANSWERED {pid}", f"last non-empty line must be `ANSWERED {pid}`; got {last[:80]!r}")
    g.add(f"{lab} produced-files list not blank", has_list and bool(produced), "`PRODUCED FILES:` followed by `- <path>` lines")
    missing = [x for x in expected if x not in produced]
    g.add(f"{lab} produced files cover expected outputs", has_list and not missing, f"not listed: {missing}" if missing else "ok")
    absent = [x for x in produced if safe_rel(root, x) is None or not os.path.isfile(safe_rel(root, x)) or os.path.getsize(safe_rel(root, x)) == 0]
    g.add(f"{lab} produced files exist", has_list and bool(produced) and not absent, f"missing or empty: {absent}" if absent else "ok")
    for x in produced:
        if not absent and safe_rel(root, x):
            g.use(x)


def promote(root, packet_id):
    """Move one captured packet to "answered", only if G0 passes with it captured. Returns (exit code, message).

    The index is rewritten only on PASS. G0 is then run again on the promoted index and must still pass."""
    from gates.common import load_json_strict, write_json_atomic
    full = os.path.join(root, INDEX)
    idx, err = load_json_strict(full)
    if err or not isinstance(idx, dict) or not isinstance(idx.get("packets"), list):
        return 2, f"{INDEX}: {err or 'packets list missing'}"
    hit = [p for p in idx["packets"] if isinstance(p, dict) and p.get("id") == packet_id]
    if len(hit) != 1:
        return 2, f"{packet_id}: not found once in {INDEX}"
    if hit[0].get("status") != "captured":
        return 1, f"{packet_id}: status is {hit[0].get('status')!r}; only a captured packet can be promoted"
    rec = g0(root)
    if rec["result"] != "PASS":
        bad = [c["check"] for c in rec["checks"] if c["result"] != "PASS"]
        return 1, f"{packet_id} stays captured: G0 FAIL on {bad}"
    hit[0]["status"] = "answered"
    write_json_atomic(idx, full)
    rec2 = g0(root)
    if rec2["result"] != "PASS":
        hit[0]["status"] = "captured"
        write_json_atomic(idx, full)
        bad = [c["check"] for c in rec2["checks"] if c["result"] != "PASS"]
        return 1, f"{packet_id} put back to captured: G0 FAIL after promotion on {bad}"
    return 0, f"{packet_id} promoted to answered; G0 PASS"


def main(argv=None):
    import sys
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 3 or a[0] != "promote":
        print("usage: python3 -m gates.packet promote <project_root> <packet id>")
        return 2
    code, msg = promote(a[1], a[2])
    print(msg)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
