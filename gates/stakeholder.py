"""Live Stakeholder conversation for Stages 1 and 2: capture tool and the checks G1 and G2 run (docs/stages.md,
"Stage 1 and Stage 2 conversation"; docs/rules.md 31-36).

Stages 1 (decision) and 2 (question framing) run as a group chat between the Stakeholder (a role that plays the business
person, briefed only with the public brief and a persona written from it), the owner and the parent. Every Stakeholder
and owner message the stage relies on is captured exactly, one write-once read-only file per message, by this tool.
The decision document and the framing cite those captures (through registered statements) alongside the brief. The
owner locks each stage in his own words; the Stakeholder's approval is business feedback and never a lock.

Commands (all paths project-relative; each refuses and changes nothing on a bad input; exit 0 ok, 1 refused, 2 usage):
  python3 -m gates.stakeholder init <root> --stage 1|2 --brief <rel> [--persona <rel>] --run-kind live|rehearsal
  python3 -m gates.stakeholder capture <root> --stage 1|2 --id <ID> --speaker stakeholder|owner|lead
          --timestamp <ISO with zone> --text-file <file holding the exact chat text> [--label "REHEARSAL MOCK"]
  python3 -m gates.stakeholder statement <root> --stage 1|2 --id <ST id> --capture <ID> --kind <kind> --quote <text>
          [--brief-quote <text>] [--authorized-by <owner capture ID> --authorized-quote <text>]
  python3 -m gates.stakeholder lock <root> --stage 1|2 --capture <owner capture ID> --quote <text>

Files: conversation record artifacts/stage<N>/conversation.json; captures captures/stage<N>_chat/<ID>.txt plus
captures/stage<N>_chat/SHA256SUMS (sha256sum format, regenerated from the files); owner lock
artifacts/stage<N>_owner_lock.json bound to the exact hash of the stage's subject (Stage 1 decision document, Stage 2
framing).

Capture file layout (header, a line `---`, then the chat text byte for byte):
  CAPTURE_ID: S1-M01
  STAGE: 1
  SPEAKER: stakeholder
  TIMESTAMP: 2026-11-16T19:40:12-06:00
  LABEL: REHEARSAL MOCK        (only in a rehearsal)
  ---
  <exact chat text>
"""
from __future__ import annotations

import datetime
import json
import os
import re
import stat
import sys

from gates.common import (TIMESTAMP_RE, load_json_strict, ref_current, ref_of, safe_rel, sha256_file, text,
                          write_json_atomic)

SPEAKERS = ("stakeholder", "owner", "lead")
KINDS = ("brief_fact", "preference", "clarification", "twist", "rule_change")
USES = ("fact", "preference", "clarification", "twist", "rule_change", "context")
STAGES = ("1", "2")
SUBJECT = {"1": "artifacts/stage1_decision.json", "2": "artifacts/stage2_framing.json"}
SUMS = "SHA256SUMS"
MOCK_LABEL = "REHEARSAL MOCK"

# A Stakeholder input may never be one of these (docs/rules.md 32). Case-insensitive, matched on the whole path.
FORBIDDEN_INPUT_RE = re.compile(r"(^|/)(private[^/]*|original|scoring|keys?|packets|reviews?|captures|replies)(/|$)"
                                r"|answer|parent_only|evaluator|reference[_-]?sql|key[_-]?sheet", re.IGNORECASE)
# Words that mark a business preference or a gap in the brief, not a fact the brief settles (docs/rules.md 33).
PREFERENCE_RE = re.compile(r"\b(prefer\w*|rather|my (own )?(view|preference|guess)|i'?d like|i would like|"
                           r"(brief|it) (doesn'?t|does not) say|not in the brief)\b", re.IGNORECASE)
# The owner's lock must use a lock word and must not be negated or conditional (docs/rules.md 35).
LOCK_RE = re.compile(r"\b(lock(ed)?|approve[ds]?|confirm(ed)?|agree[ds]?|go ahead|sign(ed)? off|accept(ed)?)\b", re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(don'?t|do not|not|never|no|hold off|wait|until|unless|if)\b", re.IGNORECASE)
# Phrases that confirm a lock rather than negate it ("Lock it, no changes."); removed before the negation check.
CONFIRMING_NO_RE = re.compile(r"\b(no (more |further |other )?(changes?|edits?|tweaks?|revisions?|questions?)( needed)?|nothing (else |more )?to change)\b",
                              re.IGNORECASE)


def plain_lock(q):
    """True when the quote uses a lock word and is not negated or conditional (docs/rules.md 35)."""
    if not text(q) or LOCK_RE.search(q) is None:
        return False
    return NEGATION_RE.search(CONFIRMING_NO_RE.sub(" ", q)) is None
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![\w])")


class Refused(Exception):
    pass


# ------------------------------------------------------------------------------------------------ paths and parsing
def record_rel(stage):
    return f"artifacts/stage{stage}/conversation.json"


def capture_dir(stage):
    return f"captures/stage{stage}_chat"


def lock_rel(stage):
    return f"artifacts/stage{stage}_owner_lock.json"


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def numbers(s):
    out = set()
    for m in NUM_RE.finditer(s or ""):
        t = m.group(0).replace(",", "").rstrip("%").lstrip("+")
        try:
            out.add(str(float(t)))
        except ValueError:
            pass
    return out


def parse_ts(s):
    if not (isinstance(s, str) and TIMESTAMP_RE.match(s)):
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_capture(raw):
    """(header dict, body text) of a capture file, or (None, None) if the layout is wrong."""
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, None
    head, sep, body = s.partition("\n---\n")
    if not sep:
        return None, None
    h = {}
    for line in head.split("\n"):
        k, colon, v = line.partition(":")
        if not colon:
            return None, None
        h[k.strip().upper()] = v.strip()
    return h, body


def read_text(root, rel):
    full = safe_rel(root, rel)
    if full is None or not os.path.isfile(full):
        return None
    try:
        with open(full, encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        return None


def is_readonly(path):
    return os.stat(path).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0


# ------------------------------------------------------------------------------------------------ tool (writes)
def _load_record(root, stage):
    obj, err = load_json_strict(os.path.join(root, record_rel(stage)))
    if err:
        raise Refused(f"{record_rel(stage)} {err}; run init first")
    return obj


def _save_record(root, stage, rec):
    write_json_atomic(rec, os.path.join(root, record_rel(stage)))


def init(root, stage, brief, persona=None, run_kind="live"):
    if stage not in STAGES or run_kind not in ("live", "rehearsal"):
        raise Refused("stage must be 1 or 2 and run kind live or rehearsal")
    if os.path.exists(os.path.join(root, record_rel(stage))):
        raise Refused(f"{record_rel(stage)} exists; a conversation record is started once")
    refs = []
    for rel in [brief] + ([persona] if persona else []):
        r = ref_of(root, rel)
        if r["sha256"] is None:
            raise Refused(f"{rel}: not a project file")
        if FORBIDDEN_INPUT_RE.search(rel):
            raise Refused(f"{rel}: the Stakeholder may never read this path")
        refs.append(r)
    if stage == "1" and not persona:
        raise Refused("Stage 1 needs the persona the parent wrote from the brief")
    rec = {"stage": stage, "run_kind": run_kind, "brief": refs[0], "persona": refs[1] if persona else None,
           "stakeholder_inputs": refs, "capture_dir": capture_dir(stage), "captures": [], "opening": None,
           "statements": []}
    _save_record(root, stage, rec)
    return rec


def write_sums(root, stage, rec):
    d = os.path.join(root, capture_dir(stage))
    lines = [f"{sha256_file(os.path.join(root, c['path']))}  {os.path.basename(c['path'])}\n"
             for c in sorted(rec["captures"], key=lambda c: os.path.basename(c["path"]))]
    p = os.path.join(d, SUMS)
    if os.path.exists(p):
        os.chmod(p, 0o644)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(lines))
    os.chmod(p, 0o444)


def capture(root, stage, cid, speaker, timestamp, chat_bytes, label=None):
    rec = _load_record(root, stage)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", cid or ""):
        raise Refused("capture id: letters, digits, _ . - only")
    if speaker not in SPEAKERS:
        raise Refused(f"speaker must be one of {SPEAKERS}")
    if parse_ts(timestamp) is None:
        raise Refused("timestamp must be ISO 8601 with a zone, e.g. 2026-11-16T19:40:12-06:00")
    if any(c.get("id") == cid for c in rec["captures"]):
        raise Refused(f"capture {cid} already recorded; captures are write-once")
    try:
        chat_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("chat text is not UTF-8") from None
    if not chat_bytes.strip():
        raise Refused("chat text is empty")
    if rec["run_kind"] == "rehearsal" and label != MOCK_LABEL:
        raise Refused(f"a rehearsal capture must carry --label \"{MOCK_LABEL}\"")
    if rec["run_kind"] == "live" and label:
        raise Refused("a live capture carries no label")
    rel = f"{capture_dir(stage)}/{cid}.txt"
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    head = f"CAPTURE_ID: {cid}\nSTAGE: {stage}\nSPEAKER: {speaker}\nTIMESTAMP: {timestamp}\n"
    head += f"LABEL: {label}\n" if label else ""
    with open(full, "xb") as fh:          # write-once: refuses an existing file
        fh.write(head.encode("utf-8") + b"---\n" + chat_bytes)
    os.chmod(full, 0o444)
    entry = {"id": cid, "speaker": speaker, "timestamp": timestamp, "path": rel, "sha256": sha256_file(full)}
    rec["captures"].append(entry)
    if stage == "1" and speaker == "stakeholder" and rec.get("opening") is None:
        rec["opening"] = cid
    write_sums(root, stage, rec)
    _save_record(root, stage, rec)
    return entry


def _capture_body(root, rec, cid):
    c = next((c for c in rec.get("captures", []) if isinstance(c, dict) and c.get("id") == cid), None)
    if c is None:
        return None, None
    with open(os.path.join(root, c["path"]), "rb") as fh:
        return c, parse_capture(fh.read())[1]


def statement(root, stage, sid, cid, kind, quote, brief_quote=None, auth_cid=None, auth_quote=None):
    rec = _load_record(root, stage)
    if kind not in KINDS:
        raise Refused(f"kind must be one of {KINDS}")
    if any(s.get("id") == sid for s in rec["statements"]):
        raise Refused(f"statement {sid} exists")
    c, body = _capture_body(root, rec, cid)
    if c is None or norm(quote) not in norm(body):
        raise Refused(f"the quote is not in capture {cid}")
    st = {"id": sid, "capture": cid, "kind": kind, "quote": quote}
    if brief_quote:
        st["brief_quote"] = brief_quote
    if auth_cid:
        st["authorized_by"] = {"capture": auth_cid, "quote": auth_quote or ""}
    rec["statements"].append(st)
    _save_record(root, stage, rec)
    return st


def lock(root, stage, cid, quote):
    rec = _load_record(root, stage)
    c, body = _capture_body(root, rec, cid)
    if c is None or c.get("speaker") != "owner":
        raise Refused("a lock cites an owner capture; the Stakeholder's approval is never a lock")
    if norm(quote) not in norm(body):
        raise Refused(f"the quote is not in capture {cid}")
    p = os.path.join(root, lock_rel(stage))
    if os.path.exists(p):
        raise Refused(f"{lock_rel(stage)} exists; a new lock is a new version (supersede it first)")
    obj = {"stage": stage, "subject": ref_of(root, SUBJECT[stage]), "conversation": record_rel(stage),
           "capture": cid, "quote": quote}
    if obj["subject"]["sha256"] is None:
        raise Refused(f"{SUBJECT[stage]} missing")
    write_json_atomic(obj, p)
    return obj


# ------------------------------------------------------------------------------------------------ checks (G1, G2)
class Conversation:
    def __init__(self, rec, bodies, brief_text):
        self.rec = rec
        self.captures = {c["id"]: c for c in rec.get("captures", []) if isinstance(c, dict) and text(c.get("id"))}
        self.bodies = bodies
        self.statements = {s["id"]: s for s in rec.get("statements", []) if isinstance(s, dict) and text(s.get("id"))}
        self.brief_text = brief_text or ""


def _in(quote, body):
    return text(quote) and body is not None and norm(quote) in norm(body)


def conversation_checks(g, stage):
    """Every check on one stage's conversation record. Returns a Conversation (possibly partial) or None."""
    L = f"Stage {stage} chat"
    rel = record_rel(stage)
    rec = g.load(rel, f"{L} record")
    if rec is None:
        g.add(f"{L}: conversation captured", False, f"{rel} missing: Stage {stage} runs as a captured group chat with the Stakeholder")
        return None
    root = g.root
    g.add(f"{L}: record stage", str(rec.get("stage")) == stage, f"stage must equal {stage}")
    kind = rec.get("run_kind")
    g.add(f"{L}: run kind", kind in ("live", "rehearsal"), "run_kind live | rehearsal")
    brief = rec.get("brief")
    ok_brief = ref_current(root, brief)
    if ok_brief:
        g.use(brief["path"])
    g.add(f"{L}: brief current", ok_brief, "brief {path, sha256} current")
    brief_text = read_text(root, brief["path"]) if ok_brief else None
    # Stakeholder isolation (rules 32): exactly the brief and the persona, nothing forbidden.
    persona = rec.get("persona")
    inputs = rec.get("stakeholder_inputs")
    if stage == "1" or persona is not None:
        ok_p = ref_current(root, persona)
        if ok_p:
            g.use(persona["path"])
        ptxt = read_text(root, persona["path"]) if ok_p else None
        g.add(f"{L}: persona written from the brief", ok_p and ok_brief and ptxt is not None
              and os.path.basename(brief["path"]) in ptxt, "persona {path, sha256} current and names the brief file")
    want = {r["path"] for r in (brief, persona) if isinstance(r, dict) and text(r.get("path"))}
    got = [r for r in inputs] if isinstance(inputs, list) else None
    got_paths = {r.get("path") for r in got if isinstance(r, dict)} if got is not None else None
    bad = sorted(p for p in (got_paths or set()) if not text(p) or FORBIDDEN_INPUT_RE.search(p))
    g.add(f"{L}: Stakeholder reads only the brief and the persona",
          got is not None and got_paths == want and not bad and all(ref_current(root, r) for r in got),
          f"stakeholder_inputs must be exactly {sorted(want)}, current" + (f"; forbidden: {bad}" if bad else "")
          + (f"; got {sorted(p for p in got_paths if p)}" if got_paths is not None and got_paths != want else ""))
    # Captures (rule 31).
    caps = rec.get("captures")
    caps = caps if isinstance(caps, list) else []
    cdir = capture_dir(stage)
    ids = [c.get("id") for c in caps if isinstance(c, dict)]
    shape_bad = [c.get("id") if isinstance(c, dict) else c for c in caps if not (
        isinstance(c, dict) and text(c.get("id")) and c.get("speaker") in SPEAKERS and parse_ts(c.get("timestamp"))
        and c.get("path") == f"{cdir}/{c.get('id')}.txt")]
    g.add(f"{L}: captures well-formed", bool(caps) and not shape_bad and len(set(ids)) == len(ids),
          f"captures [{{id, speaker {SPEAKERS}, timestamp ISO with zone, path {cdir}/<id>.txt}}], ids unique"
          + (f"; bad: {shape_bad}" if shape_bad else ""))
    stale, writable, header_bad, label_bad, bodies = [], [], [], [], {}
    for c in caps:
        if not isinstance(c, dict) or not text(c.get("path")):
            continue
        if not ref_current(root, c):
            stale.append(c.get("id"))
            continue
        g.use(c["path"])
        full = os.path.join(root, c["path"])
        if not is_readonly(full):
            writable.append(c["id"])
        with open(full, "rb") as fh:
            h, body = parse_capture(fh.read())
        if h is None or h.get("CAPTURE_ID") != c["id"] or h.get("STAGE") != stage or h.get("SPEAKER") != c.get("speaker") \
                or h.get("TIMESTAMP") != c.get("timestamp"):
            header_bad.append(c["id"])
            continue
        bodies[c["id"]] = body
        lab = h.get("LABEL", "")
        if (kind == "live" and ("MOCK" in lab.upper() or "REHEARSAL" in lab.upper())) or (kind == "rehearsal" and lab != MOCK_LABEL):
            label_bad.append(c["id"])
    g.add(f"{L}: capture hashes generated from the files", not stale,
          "each capture's sha256 equals the file's sha256" + (f"; mismatched or missing: {stale}" if stale else ""))
    g.add(f"{L}: captures read-only", not writable, "chmod a-w on every capture" + (f"; writable: {writable}" if writable else ""))
    g.add(f"{L}: capture headers match the record", not header_bad, "CAPTURE_ID, STAGE, SPEAKER, TIMESTAMP" + (f"; bad: {header_bad}" if header_bad else ""))
    g.add(f"{L}: rehearsal mocks never count as live", not label_bad,
          f"live run: no mock label; rehearsal: every capture labelled {MOCK_LABEL}" + (f"; bad: {label_bad}" if label_bad else ""))
    sums_rel = f"{cdir}/{SUMS}"
    sums_txt = read_text(root, sums_rel)
    if sums_txt is not None:
        g.use(sums_rel)
    want_lines = sorted(f"{c['sha256']}  {os.path.basename(c['path'])}" for c in caps
                        if isinstance(c, dict) and c.get("id") not in stale and text(c.get("sha256")) and text(c.get("path")))
    got_lines = sorted(x for x in (sums_txt or "").split("\n") if x.strip())
    g.add(f"{L}: SHA256SUMS lists every capture", sums_txt is not None and got_lines == want_lines and not stale,
          f"{sums_rel} in sha256sum format, one line per capture, generated from the files")
    conv = Conversation(rec, bodies, brief_text)
    who = {cid: c.get("speaker") for cid, c in conv.captures.items()}
    if stage == "1":
        op = rec.get("opening")
        st_caps = sorted((parse_ts(c["timestamp"]), cid) for cid, c in conv.captures.items()
                         if c.get("speaker") == "stakeholder" and parse_ts(c.get("timestamp")))
        g.add(f"{L}: Stakeholder opened the case", text(op) and who.get(op) == "stakeholder" and bool(st_caps) and st_caps[0][1] == op,
              "opening = the Stakeholder's first captured message")
    else:
        g.add(f"{L}: Stakeholder took part", "stakeholder" in who.values(), "at least one captured Stakeholder message in Stage 2")
    statement_checks(g, L, conv)
    return conv


def _authorized(conv, s):
    """True when the statement is the owner's own words, or an owner capture authorises it (quote in that capture)."""
    if conv.captures.get(s.get("capture"), {}).get("speaker") == "owner":
        return True
    a = s.get("authorized_by")
    return (isinstance(a, dict) and conv.captures.get(a.get("capture"), {}).get("speaker") == "owner"
            and _in(a.get("quote"), conv.bodies.get(a.get("capture"))))


def statement_checks(g, L, conv):
    sts = conv.rec.get("statements")
    sts = sts if isinstance(sts, list) else None
    g.add(f"{L}: statements listed", sts is not None, "statements: [{id, capture, kind, quote, ...}]")
    shape, missing, fact_bad, pref_fact, rule_bad, num_bad = [], [], [], [], [], []
    brief_nums = numbers(conv.brief_text)
    for s in sts or []:
        if not (isinstance(s, dict) and text(s.get("id")) and s.get("kind") in KINDS and text(s.get("quote"))):
            shape.append(s.get("id") if isinstance(s, dict) else s)
            continue
        if not _in(s["quote"], conv.bodies.get(s.get("capture"))):
            missing.append(s["id"])
            continue
        speaker = conv.captures[s["capture"]].get("speaker")
        if s["kind"] == "brief_fact":
            if not _in(s.get("brief_quote"), conv.brief_text):
                fact_bad.append(s["id"])
            if PREFERENCE_RE.search(s["quote"]):
                pref_fact.append(s["id"])
        if s["kind"] in ("rule_change", "twist") and not _authorized(conv, s):
            rule_bad.append(s["id"])
        if speaker == "stakeholder" and not (s["kind"] in ("rule_change", "twist") and _authorized(conv, s)):
            extra = numbers(s["quote"]) - brief_nums
            if extra:
                num_bad.append(f"{s['id']}: {sorted(extra)}")
    g.add(f"{L}: statements well-formed", not shape, f"kind in {KINDS}" + (f"; bad: {shape}" if shape else ""))
    g.add(f"{L}: every statement is in its capture", not missing,
          "each statement's quote appears in the capture it names" + (f"; not captured: {missing}" if missing else ""))
    g.add(f"{L}: brief facts quote the brief", not fact_bad,
          "a brief_fact carries a brief_quote found in the brief" + (f"; bad: {fact_bad}" if fact_bad else ""))
    g.add(f"{L}: a stakeholder preference is not a brief fact", not pref_fact,
          "a statement worded as a preference or a gap in the brief is kind preference/clarification" + (f"; bad: {pref_fact}" if pref_fact else ""))
    g.add(f"{L}: rule, threshold or definition changes need an owner capture", not rule_bad,
          "a rule_change or twist is the owner's words or authorised_by an owner capture (quote in it)" + (f"; bad: {rule_bad}" if rule_bad else ""))
    g.add(f"{L}: stakeholder numbers traced to the brief", not num_bad,
          "every number in a Stakeholder statement is in the brief unless an owner capture authorises the change"
          + (f"; untraced: {num_bad}" if num_bad else ""))


def source_checks(g, label, sources, convs, brief_text):
    """The sources a decision document or framing cites: brief quotes and Stakeholder/owner statements in captures."""
    L = f"{label} sources"
    ok_list = isinstance(sources, list) and bool(sources)
    g.add(f"{L} listed", ok_list, "sources: [{brief_quote} | {statement, use} | {capture, quote, use}]")
    sources = sources if ok_list else []
    stmts, caps = {}, {}
    for c in convs:
        for sid, s in c.statements.items():
            stmts[sid] = (c, s)
        for cid in c.captures:
            caps[cid] = c
    n_brief = n_chat = 0
    bad_shape, brief_bad, uncaptured, as_fact, use_bad, cited_ts = [], [], [], [], [], []
    for i, s in enumerate(sources):
        if not isinstance(s, dict):
            bad_shape.append(i)
            continue
        if "brief_quote" in s and len(s) == 1:
            n_brief += 1
            if not _in(s["brief_quote"], brief_text):
                brief_bad.append(i)
            continue
        use = s.get("use")
        if use not in USES:
            bad_shape.append(i)
            continue
        if text(s.get("statement")) and set(s) <= {"statement", "use"}:
            n_chat += 1
            hit = stmts.get(s["statement"])
            if hit is None or not _in(hit[1].get("quote"), hit[0].bodies.get(hit[1].get("capture"))):
                uncaptured.append(s["statement"])
                continue
            conv, st = hit
            cited_ts.append(parse_ts(conv.captures[st["capture"]]["timestamp"]))
            if use == "fact" and st.get("kind") != "brief_fact":
                as_fact.append(s["statement"])
            elif use in ("rule_change", "twist") and (st.get("kind") != use or not _authorized(conv, st)):
                use_bad.append(s["statement"])
        elif text(s.get("capture")) and set(s) <= {"capture", "quote", "use"}:
            n_chat += 1
            conv = caps.get(s["capture"])
            if conv is None or not _in(s.get("quote"), conv.bodies.get(s["capture"])):
                uncaptured.append(f"{s['capture']}: {s.get('quote')!r}")
                continue
            cited_ts.append(parse_ts(conv.captures[s["capture"]]["timestamp"]))
            if use == "fact":
                as_fact.append(s["capture"])
            elif use in ("rule_change", "twist"):
                use_bad.append(s["capture"])
        else:
            bad_shape.append(i)
    g.add(f"{L} well-formed", not bad_shape, f"use in {USES}" + (f"; bad entries: {bad_shape}" if bad_shape else ""))
    g.add(f"{L} cite the brief and the captures", n_brief > 0 and n_chat > 0, f"brief quotes {n_brief}, chat citations {n_chat}")
    g.add(f"{L}: brief quotes are in the brief", not brief_bad, f"bad entries: {brief_bad}" if brief_bad else "all found")
    g.add(f"{L}: every stakeholder statement cited is in a capture", not uncaptured,
          "cited statements and quotes found in a current capture" + (f"; not captured: {uncaptured}" if uncaptured else ""))
    g.add(f"{L}: no preference or chat remark used as a brief fact", not as_fact,
          "use 'fact' only for a brief_fact statement" + (f"; bad: {as_fact}" if as_fact else ""))
    g.add(f"{L}: rule changes cited only with owner authority", not use_bad,
          "use rule_change/twist only for an owner-authorised statement of that kind" + (f"; bad: {use_bad}" if use_bad else ""))
    return [t for t in cited_ts if t is not None]


def lock_checks(g, stage, conv, cited_ts):
    """The owner locks the stage in his own words; Stakeholder approval never counts (rule 35)."""
    L = f"Stage {stage} owner lock"
    rel = lock_rel(stage)
    lk = g.load(rel, L)
    if lk is None:
        g.add(f"{L}: owner's own words captured", False, f"{rel} missing")
        return
    subj = lk.get("subject")
    g.add(f"{L}: for the current {SUBJECT[stage]}", isinstance(subj, dict) and subj.get("path") == SUBJECT[stage]
          and ref_current(g.root, subj), "subject {path, sha256} = the current file")
    g.add(f"{L}: names this stage's conversation", lk.get("conversation") == record_rel(stage), f"conversation = {record_rel(stage)}")
    cid = lk.get("capture")
    c = conv.captures.get(cid) if conv else None
    body = conv.bodies.get(cid) if conv else None
    g.add(f"{L}: owner's own words (Stakeholder approval never counts)", c is not None and c.get("speaker") == "owner",
          f"capture {cid!r} speaker is {c.get('speaker') if c else 'not captured'}; must be owner")
    q = lk.get("quote")
    g.add(f"{L}: quote is in the owner capture", _in(q, body), "quote found in the capture")
    g.add(f"{L}: plain lock words", plain_lock(q),
          "the quote says lock/approve/confirm/agree/go ahead/sign off/accept, not negated or conditional ('no changes' is fine)")
    t = parse_ts(c.get("timestamp")) if c else None
    late = t is not None and all(t >= x for x in cited_ts)
    g.add(f"{L}: after every message it relies on", late, "the lock capture is not earlier than any cited capture")


# ------------------------------------------------------------------------------------------------ CLI
def _args(a):
    out, pos, i = {}, [], 0
    while i < len(a):
        if a[i].startswith("--"):
            if i + 1 >= len(a):
                raise Refused(f"{a[i]} needs a value")
            out[a[i][2:].replace("-", "_")] = a[i + 1]
            i += 2
        else:
            pos.append(a[i])
            i += 1
    return pos, out


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2 or a[0] not in ("init", "capture", "statement", "lock") or not os.path.isdir(a[1]):
        print(__doc__)
        return 2
    cmd, root = a[0], a[1]
    try:
        _, o = _args(a[2:])
        stage = o.get("stage")
        if stage not in STAGES:
            raise Refused("--stage 1 or 2")
        if cmd == "init":
            res = init(root, stage, o["brief"], o.get("persona"), o.get("run_kind", "live"))
        elif cmd == "capture":
            with open(o["text_file"], "rb") as fh:
                res = capture(root, stage, o["id"], o["speaker"], o["timestamp"], fh.read(), o.get("label"))
        elif cmd == "statement":
            res = statement(root, stage, o["id"], o["capture"], o["kind"], o["quote"], o.get("brief_quote"),
                            o.get("authorized_by"), o.get("authorized_quote"))
        else:
            res = lock(root, stage, o["capture"], o["quote"])
    except (Refused, KeyError, FileNotFoundError, FileExistsError) as e:
        print(json.dumps({"result": "REFUSED", "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps({"result": "OK", cmd: res}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
