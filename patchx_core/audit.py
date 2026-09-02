# -*- coding: utf-8 -*-
"""Kiem tra kien truc patch va nang cap tu dong.

Nguyen tac: chi tu sua nhung phan an toan (metadata, the dong, trung lap,
chuan hoa dinh dang, zip long nhau); noi dung regex/smali giu nguyen goc de
khong lam thay doi cau truc va gay lỗi.
"""

import io
import os
import re
import zipfile

from .model import Patch
from .optimizer import dedupe_sections, render_patch_text, rebuild_patch
from .parser import parse_patch_file, parse_text, _decode

LEVEL_INFO = "thông-tin"
LEVEL_WARN = "cảnh-báo"
LEVEL_ERROR = "lỗi"

# Cac duong dan target hop le (so khớp tien to)
SAFE_TARGET_ROOTS = ("AndroidManifest.xml", "smali", "res", "assets", "lib",
                     "classes", "resources.arsc")

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
GROUP_RE = re.compile(r"\$\{GROUP(\d+)\}")
ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")


class Finding:
    def __init__(self, code, level, message, fixable=False):
        self.code = code
        self.level = level
        self.message = message
        self.fixable = fixable

    def to_dict(self):
        return {"code": self.code, "level": self.level,
                "message": self.message, "fixable": self.fixable}


def audit_patch(patch):
    """Tra ve danh sach Finding cho mot patch."""
    findings = []
    labels = set()

    # A01 — metadata
    if not patch.min_engine_ver:
        findings.append(Finding("A01", LEVEL_WARN,
                                "Thieu [MIN_ENGINE_VER] — them mac dinh 2",
                                fixable=True))
    if not patch.author:
        findings.append(Finding("A01", LEVEL_WARN,
                                "Thieu [AUTHOR] — them mac dinh patchx",
                                fixable=True))
    if not patch.package:
        findings.append(Finding("A01", LEVEL_WARN,
                                "Thieu [PACKAGE] — them mac dinh *",
                                fixable=True))
    if patch.min_engine_ver:
        try:
            if int(patch.min_engine_ver) < 2:
                findings.append(Finding("A14", LEVEL_INFO,
                                        "MIN_ENGINE_VER=%s cu hon khuyen nghi 2"
                                        % patch.min_engine_ver))
        except ValueError:
            findings.append(Finding("A14", LEVEL_WARN,
                                    "MIN_ENGINE_VER khong phai so: %s"
                                    % patch.min_engine_ver))

    for sec in patch.sections:
        t = sec.type
        if t in ("MIN_ENGINE_VER", "AUTHOR", "PACKAGE"):
            continue

        # A02 — the dong
        if not sec.closed:
            findings.append(Finding("A02", LEVEL_WARN,
                                    "[%s] thieu the dong [/%s] (khối %d)"
                                    % (t, t, sec.order), fixable=True))

        # A04 — khoa bat buoc
        for key in ("TARGET", "MATCH"):
            if t in ("MATCH_REPLACE", "MATCH_ASSIGN", "MATCH_GOTO") \
                    and key not in sec.body:
                findings.append(Finding("A04", LEVEL_ERROR,
                                        "[%s] thieu khoa %s (khối %d)"
                                        % (t, key, sec.order)))
            elif key in sec.body and not sec.get(key).strip() and t != "GOTO":
                findings.append(Finding("A04", LEVEL_WARN,
                                        "[%s] %s rong (khối %d)"
                                        % (t, key, sec.order)))
        if t == "MATCH_REPLACE" and "REPLACE" not in sec.body:
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[MATCH_REPLACE] thieu khoa REPLACE (khối %d)"
                                    % sec.order))
        elif t == "MATCH_REPLACE" and not sec.get("REPLACE").strip():
            findings.append(Finding("A15", LEVEL_INFO,
                                    "[MATCH_REPLACE] REPLACE rong (khối %d) — "
                                    "co the la thao tac xoa co chu dich" % sec.order))
        if t == "ADD_FILES" and "SOURCE" not in sec.body:
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[ADD_FILES] thieu SOURCE (khối %d)" % sec.order))
        if t == "REPLACE_FILES" and "SOURCE" not in sec.body:
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[REPLACE_FILES] thieu SOURCE (khối %d)"
                                    % sec.order))
        if t == "REPLACE_FILES" and not (sec.get("TARGET") or "").strip():
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[REPLACE_FILES] thieu TARGET (khối %d)"
                                    % sec.order))
        if t == "SET_BOOL":
            for key in ("TARGET", "MATCH", "VALUE"):
                if key not in sec.body:
                    findings.append(Finding("A04", LEVEL_ERROR,
                                            "[SET_BOOL] thieu khoa %s (khối %d)"
                                            % (key, sec.order)))
            value = sec.get("VALUE").strip().lower()
            if value and value not in ("true", "false", "1", "0", "0x0", "0x1"):
                findings.append(Finding("A04", LEVEL_ERROR,
                                        "[SET_BOOL] VALUE khong hop le: %r "
                                        "(khối %d)" % (value, sec.order)))
        if t == "INIT" and "CODE" not in sec.body:
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[INIT] thieu khoa CODE (khối %d)" % sec.order))
        if t == "HOOK_SCRIPT" and "SOURCE" not in sec.body:
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[HOOK_SCRIPT] thieu khoa SOURCE (khối %d)"
                                    % sec.order))
        if t in ("TRACE", "API_LOG"):
            for key in ("TARGET", "MATCH"):
                if key not in sec.body:
                    findings.append(Finding("A04", LEVEL_ERROR,
                                            "[%s] thieu khoa %s (khối %d)"
                                            % (t, key, sec.order)))
        if t == "REMOTE_CONFIG" and "CONFIG_URL" not in sec.body:
            findings.append(Finding("A04", LEVEL_ERROR,
                                    "[REMOTE_CONFIG] thieu khoa CONFIG_URL "
                                    "(khối %d)" % sec.order))
        if t in ("ADD_FILES", "REPLACE_FILES", "MERGE", "EXECUTE_DEX",
                 "HOOK_SCRIPT"):
            src = sec.get("SOURCE") or sec.get("SCRIPT")
            if src and src.strip() and src.strip() not in patch.assets:
                if not patch.asset_root or not os.path.isfile(
                    os.path.join(patch.asset_root, src.strip())):
                    findings.append(Finding("A09", LEVEL_WARN,
                                            "[%s] tham chieu tai nguyen khong "
                                            "co trong patch: %s (khối %d)"
                                            % (t, src.strip(), sec.order)))

        # A05 — regex khong bien dich duoc
        if t in ("MATCH_REPLACE", "MATCH_ASSIGN", "MATCH_GOTO",
                 "LAUNCHER_ACTIVITIES", "ACTIVITIES", "APPLICATION",
                 "SET_BOOL", "TRACE", "API_LOG"):
            if sec.get("REGEX", "").strip().lower() in ("true", "1") \
                    and sec.get("MATCH").strip():
                try:
                    flags = re.DOTALL if sec.get("DOTALL", "").strip().lower() \
                        in ("true", "1") else 0
                    re.compile(sec.get("MATCH"), flags)
                except re.error as e:
                    findings.append(Finding("A05", LEVEL_ERROR,
                                            "[%s] regex lỗi (khối %d): %s"
                                            % (t, sec.order, e)))
            # A11 — GROUP vuot qua so nhóm cua mau
            if sec.get("REGEX", "").strip().lower() in ("true", "1") \
                    and sec.get("MATCH").strip():
                try:
                    n_groups = re.compile(sec.get("MATCH")).groups
                    for g in set(GROUP_RE.findall(sec.get("REPLACE"))
                                 + GROUP_RE.findall(sec.get("ASSIGN"))):
                        if int(g) > n_groups:
                            findings.append(Finding("A11", LEVEL_WARN,
                                                    "[%s] ${GROUP%s} vuot qua "
                                                    "so nhóm %d cua mau (khối %d)"
                                                    % (t, g, n_groups, sec.order)))
                except re.error:
                    pass

        # A13 — target ngoai vung chuan
        target = sec.get("TARGET").strip()
        if target and t not in ("GOTO", "DUMMY"):
            pseudo = target.startswith("[") and target.endswith("]")
            safe = any(target == r or target.startswith(r + "/")
                       or target.startswith(r) and "*" in target
                       for r in SAFE_TARGET_ROOTS)
            if not pseudo and not safe and not target.startswith("["):
                findings.append(Finding("A13", LEVEL_WARN,
                                        "[%s] TARGET ngoai vung chuan: %s "
                                        "(khối %d)" % (t, target, sec.order)))

        # Nhan cho GOTO
        if sec.name:
            labels.add(sec.name)
        if t == "DUMMY" and sec.get("NAME").strip():
            labels.add(sec.get("NAME").strip())

    # A06 — GOTO tro nhan khong ton tai
    for sec in patch.sections:
        if sec.type in ("GOTO", "MATCH_GOTO"):
            label = sec.get("GOTO").strip()
            if label and label not in labels:
                findings.append(Finding("A06", LEVEL_ERROR,
                                        "GOTO tro nhan khong ton tai: %s"
                                        % label, fixable=False))

    # A07/A08 — bien ASSIGN
    assigned = set()
    for sec in patch.sections:
        for part in sec.get("ASSIGN").splitlines():
            m = ASSIGN_RE.match(part)
            if m:
                assigned.add(m.group(1))
    used = set()
    for sec in patch.sections:
        for v in VAR_RE.findall(sec.get("REPLACE") + "\n" + sec.get("ASSIGN")
                                + "\n" + sec.get("GOTO")):
            if v.startswith("GROUP"):
                continue
            used.add(v)
    for v in sorted(used - assigned):
        findings.append(Finding("A07", LEVEL_WARN,
                                "Bien ${%s} duoc dung nhung chua duoc gan" % v))
    for v in sorted(assigned - used):
        findings.append(Finding("A08", LEVEL_INFO,
                                "Bien ${%s} duoc gan nhung khong dung toi" % v))

    # A10 — trung lap khối trong cung patch
    _, removed = dedupe_sections(patch)
    if removed:
        findings.append(Finding("A10", LEVEL_INFO,
                                "Co %d khối trung lap — co the gop" % removed,
                                fixable=True))

    # A12 — chuan hoa dinh dang
    raw = getattr(patch, "_raw_text", "")
    if "\r" in raw:
        findings.append(Finding("A12", LEVEL_INFO,
                                "Tep dung CRLF — chuan hoa ve LF", fixable=True))
    if raw.startswith("\ufeff"):
        findings.append(Finding("A12", LEVEL_INFO,
                                "Tep co BOM — loại bo", fixable=True))
    return findings


def upgrade_patch(patch, header=None):
    """Nang cap patch: metadata du, the dong du, gop trung, dinh dang chuan."""
    new_patch = rebuild_patch(patch, header=header)
    sections, _ = dedupe_sections(new_patch)
    new_patch.sections = sections
    _convert_literal_regex(new_patch)
    return new_patch


def _convert_literal_regex(patch):
    """Chuyen rule regex thuan literal sang REGEX=false de quet nhanh.

    Chi chuyen khi MATCH hoan toan la chuoi literal (re.escape khong doi
    noi dung) — khi do text.count cho ket qua giong het re.findall, nen
    scanner di duong literal nhanh (rg -F) ma khong doi hanh vi.
    """
    for sec in patch.sections:
        if sec.type not in ("MATCH_REPLACE", "MATCH_ASSIGN", "MATCH_GOTO"):
            continue
        if sec.get("REGEX", "").strip().lower() not in ("true", "1"):
            continue
        m = sec.get("MATCH", "").strip()
        if m and re.escape(m) == m:
            sec.body["REGEX"] = "false"


def parse_nested_zip(path):
    """Truong hop zip ngoai khong co patch.txt nhung chua zip con co patch.txt."""
    found = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            if name.lower().endswith(".zip"):
                try:
                    inner = zipfile.ZipFile(io.BytesIO(zf.read(name)))
                except zipfile.BadZipFile:
                    continue
                patch_entry = None
                for n in inner.namelist():
                    if n.lower() == "patch.txt" \
                            or n.lower().endswith("/patch.txt"):
                        patch_entry = n
                        break
                if patch_entry is None:
                    continue
                text = _decode(inner.read(patch_entry))
                p = parse_text(text)
                p.source = os.path.join(path, name)
                p.assets = {n: inner.read(n) for n in inner.namelist()
                            if n != patch_entry and not n.endswith("/")}
                found.append(p)
    return found


def upgrade_zip(path, out_dir, dry_run=False, header=None):
    """Tao ban nang cap cho mot zip patch; xu ly ca zip long nhau."""
    results = []
    try:
        patch = parse_patch_file(path)
        new_patch = upgrade_patch(patch, header=header)
        out_name = os.path.splitext(os.path.basename(path))[0] + ".zip"
        results.append((path, new_patch, out_name))
    except ValueError:
        # Khong co patch.txt truc tiep — thu zip long nhau
        nested = parse_nested_zip(path)
        for p in nested:
            new_patch = upgrade_patch(p, header=header)
            inner_name = os.path.splitext(os.path.basename(p.source))[0]
            out_name = "%s_%s.zip" % (os.path.splitext(os.path.basename(path))[0],
                                      inner_name)
            results.append((path, new_patch, out_name))
        if not nested:
            raise
    if dry_run:
        return results
    os.makedirs(out_dir, exist_ok=True)
    for src, new_patch, out_name in results:
        out_path = os.path.join(out_dir, out_name)
        text = render_patch_text(new_patch, header=header)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("patch.txt", text)
            for name, data in new_patch.assets.items():
                zf.writestr(name, data)
    return results
