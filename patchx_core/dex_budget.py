# -*- coding: utf-8 -*-
"""P5 — DEX Resource Manager.

Uoc luong so method/field/class refs cua cây APK da giai ma (tu smali),
du bao delta khi ap patch, va phan loại mức an toan theo gioi han 64K
cua method_ids.

Muc: SAFE / WATCH / HIGH / CRITICAL / BLOCK.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor

DEX_METHOD_MAX = 65536  # gioi han method_ids cua mot dex (64K)

_METHOD_DECL_RE = re.compile(r"^\.method\b[^\n]*", re.M)
_FIELD_DECL_RE = re.compile(r"^\.field\b[^\n]*", re.M)
_INVOKE_RE = re.compile(
    r"\binvoke-(?:static|virtual|direct|super|interface|"
    r"static/range|virtual/range|direct/range|super/range|"
    r"interface/range|polymorphic|polymorphic/range)"
    r"\s*\{[^}]*\},\s*(L[^;]+;)->", re.M)
_FIELD_REF_RE = re.compile(
    r"\b(?:s|i)(?:get|put)(?:-boolean|-byte|-char|-short|-int|-long|"
    r"-float|-double|-object|-wide)?\s+[vp\d]+,\s*(L[^;]+;)->", re.M)
_STRING_RE = re.compile(r"const-string(?:/jumbo)?\s+[vp\d]+,\s*\"", re.M)
_NEW_INSTANCE_RE = re.compile(r"new-instance\s+[vp\d]+,\s*(L[^;]+;)", re.M)

# Uoc luong delta method refs theo LOAI khối patch (gia tri than trong)
BLOCK_DELTA_EST = {
    "TRACE": 2,          # Log.d + marker class
    "API_LOG": 2,
    "INIT": 2,           # invoke class helper
    "HOOK_SCRIPT": 3,    # class helper + invoke-static
    "REMOTE_CONFIG": 3,  # helper + init
    "EXECUTE_DEX": 10,   # khong biet trước — mac dinh than trong
    "MERGE": 5,
    "ADD_FILES": 5,
    "REPLACE_FILES": 2,
    "SET_BOOL": 0,       # chi sua literal
    "MATCH_REPLACE": 0,
    "MATCH_ASSIGN": 0,
    "MATCH_GOTO": 0,
    "REMOVE_FILES": -1,  # xoa thuong giam refs
    "GOTO": 0,
    "DUMMY": 0,
    "MIN_ENGINE_VER": 0,
    "AUTHOR": 0,
    "PACKAGE": 0,
}


def _iter_smali(tree_root):
    for dirpath, _dirs, files in os.walk(tree_root):
        for fn in files:
            if fn.endswith(".smali"):
                yield os.path.join(dirpath, fn)


def _scan_one(path):
    """Quet 1 tệp smali — tra (methods, fields, strings)."""
    methods = set()
    fields = set()
    strings = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return methods, fields, 0
    for m in _METHOD_DECL_RE.finditer(text):
        methods.add(m.group(0))
    for m in _INVOKE_RE.finditer(text):
        methods.add(m.group(0))
    for m in _FIELD_DECL_RE.finditer(text):
        fields.add(m.group(0))
    for m in _FIELD_REF_RE.finditer(text):
        fields.add(m.group(0))
    strings = len(_STRING_RE.findall(text))
    return methods, fields, strings


def analyze_tree(tree_root, max_files=None, workers=1):
    """Quet smali*/*.smali — tra dict used refs uoc luong.

    - classes:  so tệp .smali (moi tệp khai bao 1 class);
    - methods:  khai bao .method + tham chieu invoke (union);
    - fields:   khai bao .field + tham chieu get/put (union);
    - strings:  tổng const-string;
    - files:    so tệp da quet.
    - workers > 1: song song bang ThreadPoolExecutor (P20).
    """
    paths = []
    for path in _iter_smali(tree_root):
        if max_files and len(paths) >= max_files:
            break
        paths.append(path)
    classes = len(paths)
    methods = set()
    fields = set()
    strings = 0
    if workers and workers > 1 and len(paths) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, 16)) as ex:
            for m, f, st in ex.map(_scan_one, paths):
                methods |= m
                fields |= f
                strings += st
    else:
        for m, f, st in (_scan_one(p) for p in paths):
            methods |= m
            fields |= f
            strings += st
    return {
        "classes": classes,
        "methods": len(methods),
        "fields": len(fields),
        "strings": strings,
        "files": classes,
    }


def estimate_delta(sections):
    """Uoc luong tổng delta method refs tu danh sach khối patch."""
    delta = 0
    per_type = {}
    for sec in sections:
        t = sec.type
        d = BLOCK_DELTA_EST.get(t, 0)
        delta += d
        per_type[t] = per_type.get(t, 0) + d
    return delta, per_type


def classify(used, delta=0, max_refs=DEX_METHOD_MAX):
    """Phan loại mức an toan + con lai (remaining)."""
    total = used + delta
    remaining = max_refs - total
    if total >= max_refs:
        return "BLOCK", remaining, total
    ratio = total / max_refs
    if ratio >= 0.95:
        return "CRITICAL", remaining, total
    if ratio >= 0.85:
        return "HIGH", remaining, total
    if ratio >= 0.70:
        return "WATCH", remaining, total
    return "SAFE", remaining, total


def budget_report(tree_root, sections=None, max_refs=DEX_METHOD_MAX,
                  max_files=None, workers=1):
    """Bao cao day du: used / delta / mức / remaining."""
    used = analyze_tree(tree_root, max_files=max_files, workers=workers)
    delta, per_type = estimate_delta(sections or [])
    level, remaining, total = classify(used["methods"], delta, max_refs)
    return {
        "used": used,
        "delta": delta,
        "per_type": per_type,
        "total": total,
        "remaining": remaining,
        "level": level,
        "max_refs": max_refs,
    }


STRATEGY_ORDER = ("AGGRESSIVE", "EAGER", "BALANCED", "CONSERVATIVE",
                  "LOCKED")


def strategy_for(rep):
    """P6 — DEX Strategy: chon chien luoc ap patch theo mức budget.

    - AGGRESSIVE : du nhieu, tu do ap moi khối;
    - EAGER      : ap binh thuong, theo doi delta;
    - BALANCED   : chi khối delta thap, uu tien 0-delta;
    - CONSERVATIVE: chi khối 0-delta, canh bao manh;
    - LOCKED     : khong ap (BLOCK).
    """
    level = rep["level"]
    remaining = rep["remaining"]
    max_refs = rep["max_refs"]
    used = rep["used"]["methods"]
    if level == "BLOCK":
        strategy = "LOCKED"
        risk = "HIGH"
        confidence = 99
        reason = ("DEX da vuot gioi han method refs (%d/%d) — phai "
                  "giam refs trước khi ap patch." % (rep["total"], max_refs))
    elif level == "CRITICAL":
        strategy = "CONSERVATIVE"
        risk = "HIGH"
        confidence = 95
        reason = ("Con rat it cho (%d refs) — chi cho phep khối khong lam "
                  "tang method refs." % remaining)
    elif level == "HIGH":
        strategy = "BALANCED"
        risk = "MEDIUM"
        confidence = 90
        reason = ("Con %d refs — chi ap khối delta thap, uu tien khối "
                  "0-delta." % remaining)
    elif level == "WATCH":
        strategy = "EAGER"
        risk = "LOW"
        confidence = 85
        reason = ("Con %d refs — ap binh thuong, theo doi delta sau khi "
                  "ap." % remaining)
    else:
        strategy = "AGGRESSIVE"
        risk = "LOW"
        confidence = 80
        reason = ("DEX du nhieu (con %d refs) — tu do ap, van chay "
                  "valiđạtion sau apply." % remaining)
    return {
        "strategy": strategy,
        "estimated_delta": rep["delta"],
        "risk": risk,
        "confidence": confidence,
        "reason": reason,
        "remaining": remaining,
        "used": used,
    }
