"""GP assembly regression gate: every assembled large output equals the declared whole, with no omitted part.

Index: artifacts/assembly/index.json {"assemblies": [{"split": <split spec path>}]}  ([] = no large outputs, stated explicitly)
For each assembly: the transform log exists; output and part files still match the log; re-planning from the split spec and
the captured replies reproduces the output byte-for-byte; the item set equals the declared whole.
"""
from __future__ import annotations

from gates import assembly
from gates.assembly import _rb
from gates.common import Gate, load_json_strict, ref_current, safe_rel

INDEX = "artifacts/assembly/index.json"


def gp(root):
    g = Gate("GP", root)
    idx = g.load(INDEX, "Assembly index")
    items = (idx or {}).get("assemblies")
    g.add("Assemblies declared explicitly", isinstance(items, list), "assemblies: list (empty only when no large outputs)")
    for a in items if isinstance(items, list) else []:
        split = a.get("split") if isinstance(a, dict) else None
        lab = f"Assembly {split}"
        report, data, _ = assembly.plan(root, split) if isinstance(split, str) else ({"errors": ["no split path"]}, None, {})
        g.add(f"{lab}: parts valid and complete", not report["errors"], "; ".join(report["errors"][:5]) or "all parts present, markers, no duplicates")
        if data is None:
            continue
        sp = report["spec"]
        g.use(split)
        for p in report["parts"]:
            g.use(p["reply"])
        lp = safe_rel(root, sp.get("log", ""))
        log, err = load_json_strict(lp) if lp else (None, "unsafe")
        g.use(sp.get("log"))
        g.add(f"{lab}: transform log present", err is None and isinstance(log, dict), f"{sp.get('log')}: {err or 'ok'}")
        if err or not isinstance(log, dict):
            continue
        out = log.get("output") or {}
        g.add(f"{lab}: output matches log", ref_current(root, out) and out.get("path") == sp.get("output"), "output hash must equal the logged hash")
        g.use(sp.get("output"))
        pf = log.get("part_files") or []
        g.add(f"{lab}: part files current", len(pf) == len(sp["parts"]) and all(ref_current(root, x) for x in pf),
              "every logged part file present with its logged hash; one per declared part")
        cur = _rb(safe_rel(root, sp["output"])) if ref_current(root, out) else None
        g.add(f"{lab}: re-assembly equals output", cur == data, "assembled parts equal the declared whole byte-for-byte")
    return g.result()
