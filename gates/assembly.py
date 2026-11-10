"""Large-output assembly: join part replies into one declared whole, deterministically, write-once, with a transform log.

A plain large-output assembler. Split spec (JSON, project-relative):
{
  "name": "whole",
  "items_key": "case_expected",              # each part block holds {items_key: {item_id: {...}}}
  "expected_ids": ["c1", "c2", ...],         # the declared whole, in output order
  "item_required_fields": ["fixture_id", ...],
  "header": {"part": 1, "key": "header", "required_fields": ["covered_tables"]},     # optional
  "coverage": {"header_field": "covered_tables", "item_field": "tables"},            # optional
  "parts": [{"part": 1, "reply": "transcripts/x_reply.md", "end_marker": "ANSWERED X", "item_ids": [...], "extra_keys": []}],
  "output": "docs/whole.json", "log": "evidence/whole_transform_log.json", "part_dir": "artifacts/parts/whole"
}
Each reply must end with its end marker line and hold exactly one fenced block (```json or ```), extracted byte-exact.
Nothing is written unless every check passes; every write is exclusive-create (write-once).
usage: python3 -m gates.assembly ROOT SPLIT [--report-only]
"""
from __future__ import annotations

import json
import os


def _rb(p):
    with open(p, "rb") as fh:
        return fh.read()
import sys

from gates.common import load_json_strict, now_utc, safe_rel, sha256_bytes, write_once


def _loads_nodup(b):
    dups = []

    def hook(pairs):
        ks = [k for k, _ in pairs]
        dups.extend(sorted({k for k in ks if ks.count(k) > 1}))
        return dict(pairs)
    return json.loads(b.decode("utf-8"), object_pairs_hook=hook), dups


def extract_block(b):
    """(block_bytes, start, end, error). Exactly one fenced block; the opening fence on its own line."""
    if b.count(b"```") != 2:
        return None, None, None, f"expected exactly one fenced block, found {b.count(b'```')} fence markers"
    o = b.find(b"```")
    nl = b.find(b"\n", o)
    if nl < 0 or (o > 0 and b[o - 1:o] != b"\n") or b[o + 3:nl].strip() not in (b"json", b""):
        return None, None, None, "opening fence must be its own line, ```json or ```"
    s = nl + 1
    e = b.find(b"\n```", s - 1)
    if e < 0:
        return None, None, None, "closing fence not found"
    e += 1
    return b[s:e], s, e, None


def plan(root, split_rel):
    """Validate everything in memory. Returns (report, assembled_bytes or None, extracted {part: (bytes, info)})."""
    errors = []
    report = {"split": split_rel, "parts": [], "errors": errors}
    full = safe_rel(root, split_rel)
    sp, err = load_json_strict(full) if full else (None, "unsafe path")
    if err or not isinstance(sp, dict):
        errors.append(f"split spec {split_rel}: {err or 'not an object'}")
        return report, None, {}
    report["split_sha256"] = sha256_bytes(_rb(full))
    items_key = sp.get("items_key")
    expected = sp.get("expected_ids")
    parts_spec = sp.get("parts")
    if not isinstance(items_key, str) or not isinstance(expected, list) or not isinstance(parts_spec, list) or not parts_spec:
        errors.append("split spec needs items_key, expected_ids and parts")
        return report, None, {}
    if len(set(expected)) != len(expected):
        errors.append("expected_ids has duplicates")
    nums = [p.get("part") for p in parts_spec if isinstance(p, dict)]
    if nums != list(range(1, len(parts_spec) + 1)):
        errors.append(f"parts must be numbered 1..{len(parts_spec)} in order; got {nums}")
    declared = [i for p in parts_spec if isinstance(p, dict) for i in (p.get("item_ids") or [])]
    if sorted(declared) != sorted(expected) or len(set(declared)) != len(declared):
        errors.append("split item_ids across parts must partition expected_ids exactly (no omitted or repeated item)")
    hdr = sp.get("header") if isinstance(sp.get("header"), dict) else None
    req_fields = sp.get("item_required_fields") or []
    parts, extracted = {}, {}
    for p in parts_spec:
        if not isinstance(p, dict):
            errors.append("part entry is not an object")
            continue
        n, rp = p.get("part"), p.get("reply")
        r = {"part": n, "reply": rp}
        report["parts"].append(r)
        fp = safe_rel(root, rp) if isinstance(rp, str) else None
        if fp is None or not os.path.isfile(fp):
            errors.append(f"part {n}: reply missing ({rp})")
            continue
        b = _rb(fp)
        r["reply_sha256"] = sha256_bytes(b)
        lines = b.decode("utf-8", "replace").rstrip("\r\n").splitlines()
        if not lines or lines[-1].strip() != p.get("end_marker"):
            errors.append(f"part {n}: last line is not {p.get('end_marker')}")
        blk, s, e, berr = extract_block(b)
        if berr:
            errors.append(f"part {n}: {berr}")
            continue
        r.update(byte_range=[s, e], block_sha256=sha256_bytes(blk), block_bytes=len(blk))
        try:
            obj, dups = _loads_nodup(blk)
        except Exception as ex:  # noqa: BLE001
            errors.append(f"part {n}: block is not valid JSON: {ex}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"part {n}: block is not an object")
            continue
        if dups:
            errors.append(f"part {n}: duplicate keys {dups}")
        extra = set(p.get("extra_keys") or []) | ({hdr["key"]} if hdr and hdr.get("part") == n else set())
        allowed = {"part", items_key} | extra
        if set(obj) - allowed:
            errors.append(f"part {n}: unexpected top-level keys {sorted(set(obj) - allowed)}")
        if allowed - set(obj):
            errors.append(f"part {n}: missing top-level keys {sorted(allowed - set(obj))}")
        if obj.get("part") != n:
            errors.append(f"part {n}: \"part\" is {obj.get('part')!r}, expected {n}")
        items = obj.get(items_key)
        got = list(items) if isinstance(items, dict) else []
        want = list(p.get("item_ids") or [])
        if set(got) != set(want):
            errors.append(f"part {n}: item ids differ; missing {sorted(set(want) - set(got))}, extra {sorted(set(got) - set(want))}")
        r["item_ids"] = got
        r["order_as_requested"] = got == want
        for iid, v in (items.items() if isinstance(items, dict) else []):
            if not isinstance(v, dict) or not set(req_fields) <= set(v):
                errors.append(f"part {n}: {iid} lacks required fields {req_fields}")
        parts[n] = obj
        extracted[n] = (blk, r)
    allc = [c for n in sorted(parts) for c in (parts[n].get(items_key) or {})]
    if len(allc) != len(set(allc)):
        errors.append("duplicate item ids across parts: " + str(sorted({c for c in allc if allc.count(c) > 1})))
    if len(parts) == len(parts_spec) and sorted(allc) != sorted(expected):
        errors.append(f"assembled item ids != declared whole ({len(allc)} vs {len(expected)})")
    header = None
    if hdr:
        header = parts.get(hdr.get("part"), {}).get(hdr.get("key"))
        if not isinstance(header, dict) or not set(hdr.get("required_fields") or []) <= set(header):
            errors.append(f"header {hdr.get('key')} missing or lacks {hdr.get('required_fields')}")
            header = None
    cov = sp.get("coverage") if isinstance(sp.get("coverage"), dict) else None
    if cov and header is not None:
        ct = header.get(cov.get("header_field"))
        if not isinstance(ct, list) or not ct:
            errors.append(f"header.{cov.get('header_field')} missing or empty")
        else:
            for n, obj in parts.items():
                for cid, v in (obj.get(items_key) or {}).items():
                    t = v.get(cov.get("item_field")) if isinstance(v, dict) else None
                    if not isinstance(t, dict) or not set(ct) <= set(t):
                        errors.append(f"part {n}: {cid} lacks covered {sorted(set(ct) - set(t if isinstance(t, dict) else []))}")
    if errors:
        return report, None, extracted
    order = {c: i for i, c in enumerate(expected)}
    merged = {c: v for n in sorted(parts) for c, v in parts[n][items_key].items()}
    assembled = {}
    if hdr:
        assembled[hdr["key"]] = header
    for p in parts_spec:
        for k in p.get("extra_keys") or []:
            if k in assembled:
                errors.append(f"extra key {k} supplied by more than one part")
            assembled[k] = parts[p["part"]][k]
    assembled[items_key] = {c: merged[c] for c in sorted(merged, key=order.get)}
    data = (json.dumps(assembled, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if json.loads(data) != assembled:
        errors.append("re-parse of the assembled output differs")
    if errors:
        return report, None, extracted
    report["spec"] = sp
    return report, data, extracted


def assemble(root, split_rel, report_only=False):
    report, data, extracted = plan(root, split_rel)
    if report["errors"] or report_only:
        report["result"] = "FAIL" if report["errors"] else "REPORT_ONLY_OK"
        return report
    sp = report.pop("spec")

    def wx(rel, b):
        q = safe_rel(root, rel)
        if q is None:
            raise ValueError(f"unsafe output path {rel}")
        write_once(q, b)
        return {"path": rel, "sha256": sha256_bytes(b), "bytes": len(b)}
    # Refuse before writing anything if any target exists (write-once, no partial outputs).
    targets = [sp["output"], sp["log"]] + [f"{sp['part_dir']}/part_{n}.json" for n in sorted(extracted)]
    clash = [t for t in targets if safe_rel(root, t) is None or os.path.exists(safe_rel(root, t))]
    if clash:
        report["errors"].append(f"refusing to overwrite existing outputs: {clash}")
        report["result"] = "FAIL"
        return report
    part_files = []
    for n in sorted(extracted):
        blk, r = extracted[n]
        part_files.append(dict(wx(f"{sp['part_dir']}/part_{n}.json", blk), part=n,
                               source={"path": r["reply"], "sha256": r["reply_sha256"]}, byte_range=r["byte_range"]))
    out = wx(sp["output"], data)
    tool = os.path.abspath(__file__)
    log = {"recorded_at_utc": now_utc(), "tool": {"path": "gates/assembly.py", "sha256": sha256_bytes(_rb(tool))},
           "split": {"path": split_rel, "sha256": report["split_sha256"]}, "part_files": part_files, "output": out,
           "nature": "Assembled mechanically from part blocks (each extracted byte-exact, fences excluded); re-serialized with "
                     "json.dumps(indent=2, ensure_ascii=False)+LF in declared item order. No value added, removed or changed "
                     "(re-parse equality asserted).",
           "checks": {"parts": len(part_files), "items": len(sp["expected_ids"]), "equal_to_declared_whole": True, "duplicates": 0,
                      "markers_verified": True}}
    wx(sp["log"], (json.dumps(log, indent=2, ensure_ascii=False) + "\n").encode())
    report.update(result="ASSEMBLED", output=out, log=sp["log"])
    return report


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 2:
        print(__doc__)
        return 2
    rep = assemble(a[0], a[1], "--report-only" in a)
    print(json.dumps(rep, indent=1))
    return 0 if rep["result"] in ("ASSEMBLED", "REPORT_ONLY_OK") else 1


if __name__ == "__main__":
    sys.exit(main())
