# -*- coding: utf-8 -*-
"""Bo phan tich cu phap patch.txt — xu ly linh hoat cac bien the thuc te.

Ho tro:
  - khối khong co the dong (ket thuc khi gap khối moi hoac het tệp);
  - TARGET: [LAUNCHER_ACTIVITIES] — gia tri trong giong cu phap khối;
  - BOM/CRLF, the bi thut le, chu thich # ngoai gia tri;
  - tệp zip co tên entry ma hoa khong phai UTF-8.
"""

import os
import re
import zlib
import zipfile

from .model import Patch, Section

# Cac "component target" dac biet cua APK Editor
PSEUDO_TARGETS = {"[APPLICATION]", "[ACTIVITIES]", "[LAUNCHER_ACTIVITIES]"}

SECTION_RE = re.compile(r"^\s*\[(/)?([A-Z][A-Z0-9_]*)\]\s*$")
KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*):(.*)$")

# Danh sach khoa da biet — chi dong bat dau bang khoa nay moi mo gia tri moi
KNOWN_KEYS = {
    "NAME", "TARGET", "MATCH", "REGEX", "REPLACE", "ASSIGN", "GOTO", "DOTALL",
    "SOURCE", "EXTRACT", "SCRIPT", "SMALI_NEEDED", "MAIN_CLASS", "ENTRANCE",
    "PARAM", "MIN_ENGINE_VER", "AUTHOR", "PACKAGE",
    # Khối thuc thi hien dai (SET_BOOL / INIT / HOOK_SCRIPT / TRACE / API_LOG
    # / REMOTE_CONFIG)
    "VALUE", "CODE", "METHOD", "ENTRY", "TAG", "BEFORE", "AFTER",
    "CONFIG_URL", "FORCE", "HELPER",
}


def _decode(data: bytes) -> str:
    """Giai ma noi dung patch.txt; thu UTF-8 trước, roi cp1251, cp866."""
    for enc in ("utf-8", "cp1251", "cp866"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split_sections(text: str):
    """Chia van ban thanh danh sach [type, closed, lines]."""
    sections = []
    cur = None
    pending_target = False
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        m = SECTION_RE.match(line)
        pseudo = "[" + m.group(2) + "]" if m else None
        if m and not (pending_target and pseudo in PSEUDO_TARGETS):
            closing, name = m.groups()
            if closing:
                if cur and cur[0] == name:
                    cur[1] = True
                    sections.append(cur)
                    cur = None
                    pending_target = False
                elif cur:
                    # The dong lech khối — coi la noi dung de tranh mat du lieu
                    cur[2].append(line)
            else:
                if cur:
                    sections.append(cur)
                cur = [name, False, []]
                pending_target = False
        else:
            if cur is None:
                continue  # bo phan mo dau / chu thich ngoai khối
            cur[2].append(line)
            km = KEY_RE.match(line)
            is_target_key = bool(km and km.group(1) == "TARGET"
                                 and not km.group(2).strip())
            if is_target_key:
                pending_target = True
            elif line.strip():
                pending_target = False
    if cur:
        sections.append(cur)
    return sections


def _normalize_value(lines):
    """Chuan hoa gia tri:
    - bo dong trong o dau/cuoi;
    - dong dau cat thut le cua tệp (chi de trinh bay);
    - cac dong tiep theo giu nguyen (thut le smali/XML co y nghia).
    """
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if not lines:
        return ""
    first = lines[0].lstrip() if lines[0].strip() else ""
    return "\n".join([first] + lines[1:])


def _parse_body(lines) -> dict:
    """Chuyen cac dong than khối thanh dict khoa -> gia tri."""
    body = {}
    cur_key = None
    cur_lines = []
    for line in lines:
        km = KEY_RE.match(line)
        if km and km.group(1) in KNOWN_KEYS:
            if cur_key is not None:
                body[cur_key] = _normalize_value(cur_lines)
            cur_key = km.group(1)
            cur_lines = [km.group(2)]
        else:
            s = line.strip()
            if cur_key is None and (not s or s.startswith("#")):
                continue  # chu thich trước khoa dau tien
            cur_lines.append(line)
    if cur_key is not None:
        body[cur_key] = _normalize_value(cur_lines)
    return body


def parse_text(text: str) -> Patch:
    """Phan tich van ban patch.txt thanh Patch."""
    if text.startswith("\ufeff"):
        text = text[1:]
    patch = Patch(source="<chuoi>")
    order = 0
    for type_, closed, lines in _split_sections(text):
        body = _parse_body(lines)
        sec = Section(type=type_, body=body, order=order, closed=closed,
                      raw="\n".join(lines))
        if body.get("NAME", "").strip():
            sec.name = body["NAME"].strip()
        patch.sections.append(sec)
        order += 1
        if type_ in ("MIN_ENGINE_VER", "AUTHOR", "PACKAGE"):
            val = "\n".join(l.strip() for l in lines
                            if l.strip() and not l.strip().startswith("#"))
            if type_ == "MIN_ENGINE_VER":
                patch.min_engine_ver = val
            elif type_ == "AUTHOR":
                patch.author = val
            else:
                patch.package = val
    _validate(patch)
    return patch


def _validate(patch: Patch):
    """Ra soat lỗi pho bien, ghi vao patch.issues."""
    for sec in patch.sections:
        if sec.type in ("MATCH_REPLACE", "MATCH_ASSIGN", "MATCH_GOTO",
                        "REMOVE_FILES"):
            if "TARGET" not in sec.body:
                patch.issues.append("[%s] thieu khoa TARGET (khối %d)"
                                    % (sec.type, sec.order))
            elif not sec.get("TARGET").strip():
                patch.issues.append("[%s] TARGET rong (khối %d)"
                                    % (sec.type, sec.order))
        if sec.type in ("MATCH_REPLACE", "MATCH_ASSIGN", "MATCH_GOTO"):
            if "MATCH" not in sec.body:
                patch.issues.append("[%s] thieu khoa MATCH (khối %d)"
                                    % (sec.type, sec.order))
            elif not sec.get("MATCH").strip():
                patch.issues.append("[%s] MATCH rong (khối %d)"
                                    % (sec.type, sec.order))
        if sec.type == "MATCH_REPLACE" and "REPLACE" not in sec.body:
            patch.issues.append("[MATCH_REPLACE] thieu khoa REPLACE (khối %d)"
                                % sec.order)
        if sec.type == "ADD_FILES" and "SOURCE" not in sec.body:
            patch.issues.append("[ADD_FILES] thieu SOURCE (khối %d)" % sec.order)
        if sec.type == "SET_BOOL":
            for k in ("TARGET", "MATCH", "VALUE"):
                if k not in sec.body:
                    patch.issues.append("[SET_BOOL] thieu khoa %s (khối %d)"
                                        % (k, sec.order))
        if sec.type == "INIT" and "CODE" not in sec.body:
            patch.issues.append("[INIT] thieu khoa CODE (khối %d)" % sec.order)
        if sec.type == "HOOK_SCRIPT" and "SOURCE" not in sec.body:
            patch.issues.append("[HOOK_SCRIPT] thieu khoa SOURCE (khối %d)"
                                % sec.order)
        if sec.type in ("TRACE", "API_LOG"):
            for k in ("TARGET", "MATCH"):
                if k not in sec.body:
                    patch.issues.append("[%s] thieu khoa %s (khối %d)"
                                        % (sec.type, k, sec.order))
        if sec.type == "REMOTE_CONFIG" and "CONFIG_URL" not in sec.body:
            patch.issues.append("[REMOTE_CONFIG] thieu khoa CONFIG_URL (khối %d)"
                                % sec.order)
        if not sec.closed and sec.type not in (
                "MIN_ENGINE_VER", "AUTHOR", "PACKAGE"):
            patch.issues.append("[%s] khối khong co the dong (khối %d)"
                                % (sec.type, sec.order))
    if not patch.sections:
        patch.issues.append("Khong co khối lệnh nao")


def _parse_zip(path: str) -> Patch:
    """Doc patch tu tệp .zip (kem toan bo tai nguyen ben trong)."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        patch_entry = None
        for n in names:
            if n.lower() == "patch.txt" or n.lower().endswith("/patch.txt"):
                patch_entry = n
                break
        if patch_entry is None:
            raise ValueError("Khong tim thay patch.txt trong %s" % path)
        text = _decode(zf.read(patch_entry))
        patch = parse_text(text)
        patch.source = path
        for n in names:
            if n == patch_entry or n.endswith("/"):
                continue
            try:
                patch.assets[n] = zf.read(n)
            except (KeyError, RuntimeError, zlib.error, EOFError, OSError) as e:
                patch.issues.append("[ZIP] khong doc duoc asset %s: %s" % (n, e))
        return patch


def _parse_text_file(path: str, asset_root: str = None) -> Patch:
    """Doc patch tu patch.txt tren dia."""
    with open(path, "rb") as fh:
        data = fh.read()
    patch = parse_text(_decode(data))
    patch.source = path
    patch.asset_root = asset_root or os.path.dirname(os.path.abspath(path))
    return patch


def parse_patch_file(path: str) -> Patch:
    """Phan tich patch tu .zip, .txt hoac thu mức chua patch.txt."""
    if not os.path.exists(path):
        raise FileNotFoundError("Khong tim thay: %s" % path)
    if os.path.isdir(path):
        p = os.path.join(path, "patch.txt")
        if not os.path.isfile(p):
            raise ValueError("Khong tim thay patch.txt trong thu mức: %s" % path)
        return _parse_text_file(p, asset_root=path)
    if path.lower().endswith(".zip"):
        return _parse_zip(path)
    if path.lower().endswith(".txt"):
        return _parse_text_file(path)
    # Không rõ loại — thu nhu zip, neu that bai thi nhu van ban
    try:
        return _parse_zip(path)
    except (zipfile.BadZipFile, ValueError):
        return _parse_text_file(path)
