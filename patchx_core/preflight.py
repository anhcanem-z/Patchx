# -*- coding: utf-8 -*-
"""P7 — Preflight Engine: cong kiem tra TRUOC khi ap patch.

Gop cac kiem tra roi rac (package / SDK / target / dependency / conflict /
provenance / DEX budget / risk) thanh mot verdict ro rang:

    READY                  — san sang ap;
    READY_WITH_WARNING     — ap duoc nhung co canh bao;
    INCOMPATIBLE           — khong hop le cho cây nay (package/engine);
    UNSAFE                 — khong nen ap (DEX vuot gioi han...).
"""

import glob
import json
import os
import re

ENGINE_VERSION = 3  # bo suu tap dung MIN_ENGINE_VER toi da 3

_PSEUDO = ("[APPLICATION]", "[ACTIVITIES]", "[LAUNCHER_ACTIVITIES]")
_PACKAGE_RE = re.compile(r'package="([^"]+)"')
_TARGET_KEYS = ("TARGET", "SOURCE")


def _manifest_package(tree_root):
    p = os.path.join(tree_root, "AndroidManifest.xml")
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            m = _PACKAGE_RE.search(fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


def _targets_exist(tree_root, pattern):
    """Kiem tra pattern target (glob APK Editor) co khớp tệp nao khong."""
    if pattern in _PSEUDO or not pattern:
        return True
    rx = re.compile("^" + re.escape(pattern).replace(r"\*", ".*")
                    .replace(r"\?", ".") + "$")
    base = pattern.split("/", 1)[0] if "/" in pattern else pattern
    for dirpath, _dirs, files in os.walk(tree_root):
        for fn in files:
            rel = os.path.relpath(os.path.join(dirpath, fn), tree_root)
            if rx.match(rel):
                return True
    return False


def _load_provenance(tree_root):
    try:
        with open(os.path.join(tree_root, ".patchx", "provenance.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _check_conflicts(sections):
    groups = {}
    for sec in sections:
        if sec.type != "MATCH_REPLACE":
            continue
        key = (sec.get("TARGET").strip(), sec.get("MATCH"),
               sec.get("REGEX").strip())
        groups.setdefault(key, set()).add(sec.get("REPLACE"))
    return [(k[0] or "<rỗng>", len(v))
            for k, v in groups.items() if len(v) > 1]


def preflight_patch(patch, tree_root, *, dex_rep=None, max_files=None):
    """Chay toan bo cong — tra verdict + danh sach kiem tra."""
    checks = []
    manifest_pkg = _manifest_package(tree_root)

    # 1) Package — truong PACKAGE trong bo suu tap thuong la mo ta
    #    ("*", "ALL", tên chu de) chu khong phai package dich → chi canh bao
    #    khi co gia tri cu the khac manifest, khong chan.
    if patch.package and patch.package.strip() not in ("*", "ALL"):
        if manifest_pkg and patch.package != manifest_pkg:
            checks.append({"loại": "package", "mức": "cảnh-báo",
                           "nội_dung": "PACKAGE '%s' khac manifest '%s'"
                           % (patch.package, manifest_pkg)})
        else:
            checks.append({"loại": "package", "mức": "ok",
                           "nội_dung": "PACKAGE %s" % patch.package})

    # 2) Dependency engine
    if patch.min_engine_ver:
        try:
            need = int(patch.min_engine_ver)
        except ValueError:
            need = 1
        if need > ENGINE_VERSION:
            checks.append({"loại": "engine", "mức": "lỗi",
                           "nội_dung": "can engine >= %d, hien %d"
                           % (need, ENGINE_VERSION)})

    # 3) Target ton tai
    for sec in patch.sections:
        tgt = sec.get("TARGET").strip()
        if tgt and not _targets_exist(tree_root, tgt):
            checks.append({"loại": "target", "mức": "cảnh-báo",
                           "nội_dung": "TARGET '%s' khong khớp tệp nao"
                           " (khối %d)" % (tgt, sec.order)})

    # 4) Conflict
    for tgt, n in _check_conflicts(patch.sections):
        checks.append({"loại": "conflict", "mức": "cảnh-báo",
                       "nội_dung": "cung MATCH khac REPLACE (%d bien the) o %s"
                       % (n, tgt)})

    # 5) Provenance — sua tệp do patch khac tao
    prov = _load_provenance(tree_root)
    for sec in patch.sections:
        tgt = sec.get("TARGET").strip()
        if not tgt or tgt in _PSEUDO:
            continue
        rec = prov.get(tgt)
        if rec and rec.get("created_by") and rec["created_by"] != "goc":
            checks.append({"loại": "provenance", "mức": "cảnh-báo",
                           "nội_dung": "sua tệp do '%s' tao: %s"
                           % (rec["created_by"], tgt)})

    # 6) DEX budget
    from .dex_budget import budget_report
    rep = dex_rep or budget_report(tree_root, sections=patch.sections,
                                   max_files=max_files)
    if rep["level"] == "BLOCK":
        checks.append({"loại": "dex", "mức": "lỗi",
                       "nội_dung": "DEX vuot gioi han (%d/%d)"
                       % (rep["total"], rep["max_refs"])})
    elif rep["level"] in ("CRITICAL", "HIGH"):
        checks.append({"loại": "dex", "mức": "cảnh-báo",
                       "nội_dung": "DEX mức %s (con %d refs)"
                       % (rep["level"], rep["remaining"])})
    else:
        checks.append({"loại": "dex", "mức": "ok",
                       "nội_dung": "DEX %s (con %d refs)"
                       % (rep["level"], rep["remaining"])})

    # 7) Risk
    from .risk import risk_findings
    for f in risk_findings(patch):
        checks.append({"loại": "risk-" + f["loại"], "mức": "cảnh-báo",
                       "nội_dung": f["nội_dung"] + " (khối %d)" % f["khối"]})

    errors = [c for c in checks if c["mức"] == "lỗi"]
    warnings = [c for c in checks if c["mức"] == "cảnh-báo"]
    incompatible = [c for c in errors if c["loại"] in ("package", "engine")]
    unsafe = [c for c in errors if c["loại"] == "dex"]
    if unsafe:
        verdict = "UNSAFE"
    elif incompatible:
        verdict = "INCOMPATIBLE"
    elif warnings:
        verdict = "READY_WITH_WARNING"
    else:
        verdict = "READY"
    return {
        "verdict": verdict,
        "checks": checks,
        "errors": len(errors),
        "warnings": len(warnings),
        "summary": ("%s — %d lỗi, %d canh bao"
                    % (verdict, len(errors), len(warnings))),
    }
