"""Early guards added after the 2026-11-10 head-to-head (process lessons L10-L13; no case content or answers).

- placeholder_refs: `{path, sha256}` references copied from a shape template (all-zero or NOT_SET hashes, or a reference
  that is itself a design template file). The R Procedure Gate `finalize` walks every referenced JSON file
  (evidence dependency closure), so one such reference fails the whole run at the very end. G0 rejects them in packet
  inputs and G3 rejects them at the design lock, with a message that says what to fix.
- rate_ban_hits: a blanket ban on reporting rates or differences. Labeled descriptive (associational) rates are allowed and
  expected; only causal wording is restricted. G3 rejects a design that bans them.
- rate_claim_labeled: a claim that states a rate or a difference must carry a descriptive/associational (not causal) label.
"""
from __future__ import annotations

import json
import os
import re

from gates.common import PLACEHOLDER_RE, safe_rel

ZERO_SHA = re.compile(r"^0{64}$")
NOT_SET = re.compile(r"^\s*(NOT_SET__|REPLACE|PENDING|TBD|TODO|\{\{)", re.IGNORECASE)
TEMPLATE_FILE = re.compile(r"(^|/)templates/.*\.example\.json$|(^|/)design\.example\.json$")
TEMPLATE_HINT = ("copied from a shape template (for example the R repo's templates/methodology/design.example.json); "
                 "replace it with a real frozen file and its current sha256, or attach a prose summary instead of the "
                 "template JSON. R `finalize` (evidence dependency closure) would fail on it at the end of the run")


def _refs(x):
    if isinstance(x, dict):
        if "path" in x and "sha256" in x:
            yield x
        for v in x.values():
            yield from _refs(v)
    elif isinstance(x, list):
        for v in x:
            yield from _refs(v)


def _load(full):
    try:
        with open(full, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def ref_problem(ref):
    """Why a {path, sha256} reference is a template placeholder, or None."""
    p, s = ref.get("path"), ref.get("sha256")
    if isinstance(s, str) and ZERO_SHA.match(s.strip()):
        return "all-zero sha256"
    if isinstance(s, str) and NOT_SET.match(s):
        return f"placeholder sha256 {s.strip()[:24]!r}"
    if isinstance(p, str) and (NOT_SET.match(p) or PLACEHOLDER_RE.search(p)):
        return f"placeholder path {p.strip()[:40]!r}"
    if isinstance(p, str) and TEMPLATE_FILE.search(p.replace("\\", "/")):
        return "reference to a template file"
    return None


def placeholder_refs(root, rels, depth=3):
    """[(file, ref path, problem)] for every placeholder reference inside the named JSON files and inside JSON files they
    reference (up to `depth` levels). A named file that is itself a template file is reported too."""
    out, seen = [], set()

    def visit(rel, d):
        if rel in seen or not isinstance(rel, str):
            return
        seen.add(rel)
        if TEMPLATE_FILE.search(rel.replace("\\", "/")):
            out.append((rel, rel, "template file used as an input"))
        full = safe_rel(root, rel)
        if full is None or not rel.lower().endswith(".json") or not os.path.isfile(full):
            return
        obj = _load(full)
        for r in _refs(obj):
            why = ref_problem(r)
            if why:
                out.append((rel, str(r.get("path")), why))
            elif d > 0 and isinstance(r.get("path"), str):
                visit(r["path"], d - 1)

    for rel in rels:
        visit(rel, depth)
    return out


def describe(hits, limit=6):
    s = "; ".join(f"{f}: {p} ({w})" for f, p, w in hits[:limit])
    return s + (f"; +{len(hits) - limit} more" if len(hits) > limit else "")


# ------------------------------------------------------------------------------------------------ descriptive rates
_RATE_WORD = r"(?:rate\s+differences?|rates?|percentages?|percents?|proportions?|differences?\s+in\s+(?:rates?|proportions?|percentages?))"
_VERB = r"(?:report(?:ing|ed)?|show(?:ing|n)?|comput(?:e|ing|ed)|calculat(?:e|ing|ed)|present(?:ing|ed)?|publish(?:ing|ed)?|stat(?:e|ing|ed)|giv(?:e|ing|en)|includ(?:e|ing|ed)|quot(?:e|ing|ed))"
RATE_BAN_RES = [
    re.compile(r"\bno[- ]rates?\b(?:\s+rule)?", re.IGNORECASE),
    re.compile(r"\b(?:do\s+not|don't|does\s+not|must\s+not|should\s+not|shall\s+not|will\s+not|never|may\s+not|cannot|no)\s+"
               + _VERB + r"\s+(?:any\s+|the\s+|of\s+)?(?:\w+\s+){0,2}" + _RATE_WORD + r"\b", re.IGNORECASE),
    re.compile(r"\b" + _RATE_WORD + r"\s+(?:are|is)\s+(?:not\s+(?:to\s+be\s+)?(?:reported|shown|computed|allowed|permitted)|forbidden|prohibited|banned)\b",
               re.IGNORECASE),
]
CAUSAL_QUALIFIER = re.compile(r"caus|effect|impact|attribut|lift|uplift", re.IGNORECASE)


def rate_ban_hits(text):
    """Sentences that ban rates or differences outright. A sentence that only restricts causal wording
    ("do not present the rate difference as a causal effect") is allowed."""
    hits = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n+", text or ""):
        if any(rx.search(sent) for rx in RATE_BAN_RES) and not CAUSAL_QUALIFIER.search(sent):
            hits.append(sent.strip()[:160])
    return hits


def text_strings(obj):
    """Every string value inside a JSON object (keys excluded)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from text_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from text_strings(v)


RATE_FIGURE = re.compile(r"\d(?:[\d,]*\.?\d*)\s*(?:%|percent\b|per\s*cent\b|percentage\s+points?\b|pts?\b|pp\b)", re.IGNORECASE)
DESCRIPTIVE_LABEL = re.compile(r"descriptive|associational|association|not\s+causal|non-?causal", re.IGNORECASE)


def states_rate(quote):
    return isinstance(quote, str) and RATE_FIGURE.search(quote) is not None


def rate_claim_labeled(claim):
    """A rate claim is labeled when its `label` (or its quote) says descriptive/associational/not causal and its type is
    not causal (a causal rate claim also has to pass the locked claim ceiling)."""
    lab = " ".join(x for x in (claim.get("label"), claim.get("quote")) if isinstance(x, str))
    return claim.get("type") in ("descriptive", "associational", "recommendation") and DESCRIPTIVE_LABEL.search(lab) is not None
