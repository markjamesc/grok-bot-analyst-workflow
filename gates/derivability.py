"""GD public-file derivability check (docs/rules.md rule 14; lesson L10). Also run inside G0.

A role or stage may stop on a missing input or mapping (what a field value means, which entity is which, a code list,
a unit) only after the item has been checked against the public files (schema, brief, public bundle) and found not
derivable. A derivable item is recorded with its derivation and the work continues. Only a truly non-derivable item
stops, and it is escalated to the owner.

A reply that stops on such an item says so with one line per item:  `MISSING INPUT: <item>`

Input: artifacts/derivability.json
  {"public_sources": [{"path", "sha256"}],          the public schema, brief and bundle files (current, not private)
   "items": [{"id", "stage", "raised_in": "<packet id>" (optional), "item": "<the MISSING INPUT text>",
              "search_terms": ["..."],              words for the item, searched in every public source (case-insensitive)
              "derivable": true | false,
              "derivation": "...", "derived_from": ["<public source path>"],          when derivable
              "resolution": "continued" | "escalated_to_owner",
              "not_derivable_reason": "...", "escalated_at": "<ISO timestamp>",       when not derivable
              "term_hits_reviewed": [{"path", "why_not_derivable"}]}]}                  every public file that mentions a term

Checks:
- every `MISSING INPUT:` line in an answered packet's sealed reply has an item (same packet id and text);
- public sources are listed, current, and none is private or an answer key;
- a derivable item records its derivation, cites public sources it was derived from, and continues;
- a non-derivable item is escalated to the owner with a reason and timestamp, and explains, file by file, why each
  public source that mentions one of its search terms still does not settle it. Otherwise it is treated as derivable:
  re-check the file, record the derivation and continue.
"""
from __future__ import annotations

import os
import re

from gates.common import Gate, PLACEHOLDER_RE, TIMESTAMP_RE, ref_current, safe_rel, text

INDEX = "artifacts/derivability.json"
MISSING_RE = re.compile(r"^\s*MISSING INPUT:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
STAGES = {"1", "2", "2F", "3", "4", "5"}
ANSWER_KEY_NAME = re.compile(r"answer[_ -]?key", re.IGNORECASE)


def _t(x):
    return text(x) and not PLACEHOLDER_RE.search(x)


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def missing_lines(body):
    return [m.group(1) for m in MISSING_RE.finditer(body or "")]


def _read(full):
    try:
        with open(full, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def derivability_checks(g, root, raised=None, forbidden_prefixes=("private/",), prefix=""):
    """Adds the derivability checks to gate `g`. `raised`: [(packet id, item text)] from sealed replies."""
    raised = raised or []
    full = safe_rel(root, INDEX)
    if not raised and (full is None or not os.path.isfile(full)):
        return
    d = g.load(INDEX, prefix + "Derivability record") or {}
    src = d.get("public_sources")
    src = src if isinstance(src, list) else []
    paths = [s.get("path") for s in src if isinstance(s, dict)]
    bad = [p for p in paths if not text(p) or any(p.startswith(x) for x in forbidden_prefixes) or ANSWER_KEY_NAME.search(p)]
    stale = [s.get("path") for s in src if not (isinstance(s, dict) and ref_current(root, s))]
    g.add(prefix + "Public sources listed and current", bool(src) and not stale and not bad,
          "public_sources: [{path, sha256}] of the public schema, brief and bundle files"
          + (f"; not current: {stale}" if stale else "") + (f"; private or answer key: {bad}" if bad else ""))
    texts = {}
    for s in src:
        if isinstance(s, dict) and ref_current(root, s):
            g.use(s["path"])
            texts[s["path"]] = _read(safe_rel(root, s["path"])).lower()
    items = d.get("items")
    items = items if isinstance(items, list) else []
    ids = [i.get("id") for i in items if isinstance(i, dict)]
    g.add(prefix + "Items well-formed", len(ids) == len(items) and all(text(i) for i in ids) and len(set(ids)) == len(ids),
          "items: list with unique ids")
    have = {(str(i.get("raised_in") or ""), _norm(i.get("item") or "")) for i in items if isinstance(i, dict) and text(i.get("item"))}
    unchecked = [f"{pid}: {it}" for pid, it in raised if (pid, _norm(it)) not in have]
    g.add(prefix + "Every MISSING INPUT checked against public files", not unchecked,
          "each `MISSING INPUT:` line in a sealed reply needs an item with the same raised_in and item text"
          + (f"; unchecked: {unchecked}" if unchecked else ""))
    for i in items:
        i = i if isinstance(i, dict) else {}
        lab = f"{prefix}Item {i.get('id')}"
        terms = [t for t in i.get("search_terms", []) if text(t)] if isinstance(i.get("search_terms"), list) else []
        g.add(f"{lab} described", _t(i.get("item")) and str(i.get("stage", "")).upper() in STAGES and bool(terms),
              "item text, stage and search_terms required")
        hits = sorted({p for p, body in texts.items() for t in terms if t.lower() in body})
        if i.get("derivable") is True:
            df = [x for x in i.get("derived_from", []) if text(x)] if isinstance(i.get("derived_from"), list) else []
            g.add(f"{lab} derivation recorded", _t(i.get("derivation")) and bool(df) and all(x in texts for x in df),
                  "derivation text and derived_from: [public source paths] required")
            g.add(f"{lab} work continues", i.get("resolution") == "continued",
                  "a derivable item never stops a stage: resolution must be `continued`")
        elif i.get("derivable") is False:
            g.add(f"{lab} escalated to the owner", i.get("resolution") == "escalated_to_owner" and _t(i.get("not_derivable_reason"))
                  and isinstance(i.get("escalated_at"), str) and TIMESTAMP_RE.match(i["escalated_at"]) is not None,
                  "a non-derivable item stops only with resolution `escalated_to_owner`, a reason and escalated_at")
            rv = i.get("term_hits_reviewed") if isinstance(i.get("term_hits_reviewed"), list) else []
            explained = {r.get("path") for r in rv if isinstance(r, dict) and _t(r.get("why_not_derivable"))}
            open_hits = [p for p in hits if p not in explained]
            g.add(f"{lab} public mentions ruled out", not open_hits,
                  "public files mention a search term; re-check them, record the derivation and continue, or explain per file "
                  "why it does not settle the item" + (f"; unexplained: {open_hits}" if open_hits else ""))
        else:
            g.add(f"{lab} derivable decided", False, "derivable must be true or false")


def raised_in_replies(root, packets):
    """[(packet id, item)] from the sealed replies of answered packets."""
    out = []
    for p in packets:
        r = p.get("reply") if isinstance(p, dict) else None
        if p.get("status") == "answered" and ref_current(root, r):
            out += [(str(p.get("id")), it) for it in missing_lines(_read(safe_rel(root, r["path"])))]
    return out


def gd(root):
    g = Gate("GD", root)
    from gates.common import load_json_strict
    idx, _ = load_json_strict(os.path.join(root, "artifacts/packets/index.json"))
    pk = idx.get("packets") if isinstance(idx, dict) and isinstance(idx.get("packets"), list) else []
    derivability_checks(g, root, raised_in_replies(root, pk))
    if not g.checks:
        g.add("No MISSING INPUT raised", True, "no `MISSING INPUT:` line in any sealed reply and no derivability record")
    return g.result()
