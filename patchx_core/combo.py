# -*- coding: utf-8 -*-
"""Gop combo — ghep cac patch co nang luc ho tro nhau thanh mot combo toi uu.

Vi du dien hinh: patch bypass VIP + patch mod shell + patch kiem tra toan ven
-> combo "Bypass-VIP/License + Mod-Shell + Check-Toan-Ven".

Nguyen tac an toan:
  - chi gop cac patch khong xung dot (cung MATCH khac REPLACE phai tach);
  - nhan GOTO/NAME duoc đạt tien to theo tung patch khi gop;
  - moi combo kem danh sach nguon va so khối lệnh.
"""

import glob
import json
import os
import time

from .optimizer import (patch_capabilities, CAP_LABELS, CAP_ORDER, SYNERGY,
                        merge_patches, find_conflicts, render_patch_text)
from .parser import parse_patch_file
from .audit import parse_nested_zip


def pack_non_conflicting(patches):
    """Goi cac patch KHONG xung dot vao cung nhóm; xung dot tach rieng."""
    conflicts = find_conflicts(patches)
    conf_sets = [set(c["patches"]) for c in conflicts]

    def clashes(p, group):
        for q in group:
            if any(p.name in cs and q.name in cs for cs in conf_sets):
                return True
        return False

    groups = []
    for p in patches:
        placed = False
        for g in groups:
            if not clashes(p, g):
                g.append(p)
                placed = True
                break
        if not placed:
            groups.append([p])
    return groups, conflicts


def collect_patches(root, recursive=True):
    """Nap moi patch .zip; quet de quy thu mức con neu can."""
    patches = []
    if recursive:
        for r, dirs, _files in os.walk(root):
            if "_patchx" in r.split(os.sep):
                continue
            for f in sorted(os.listdir(r)):
                if not f.lower().endswith(".zip"):
                    continue
                path = os.path.join(r, f)
                try:
                    patches.append(parse_patch_file(path))
                except ValueError:
                    patches.extend(parse_nested_zip(path))
                except Exception:
                    pass
    else:
        for z in sorted(glob.glob(os.path.join(root, "*.zip"))):
            try:
                patches.append(parse_patch_file(z))
            except ValueError:
                patches.extend(parse_nested_zip(z))
            except Exception:
                pass
    return patches


def combo_label(caps):
    return "+".join(CAP_LABELS.get(c, c) for c in caps)


def build_combos(patches, only=None):
    """Xay danh sach combo.

    only: danh sach nang luc bat buoc, vi du
          ["bypass-license", "shell", "integrity"].
    Mac dinh: combo vi du (bypass + shell + toan ven) va moi cap synergy.
    """
    by_cap = {}
    for p in patches:
        for c in patch_capabilities(p):
            by_cap.setdefault(c, []).append(p)

    combos = []

    def add_combo(caps):
        selected = []
        for c in caps:
            selected.extend(by_cap.get(c, []))
        if not selected:
            return
        # Loai trung tên patch, giu thu tu nang luc uu tien
        unique = []
        seen = set()
        for c in caps:
            for p in by_cap.get(c, []):
                if p.name not in seen:
                    seen.add(p.name)
                    unique.append(p)
        packs, conflicts = pack_non_conflicting(unique)
        for i, pack in enumerate(packs):
            merged = merge_patches(pack, "+".join(caps))
            label = combo_label(caps)
            file_label = label.replace("/", "-").replace("\\", "-")
            suffix = "" if len(packs) == 1 else "_%d" % (i + 1)
            combos.append({
                "caps": caps,
                "label": label,
                "file": file_label + suffix + ".patch",
                "patches": [p.name for p in pack],
                "sections": len(merged.sections),
                "conflicts": len(conflicts),
                "merged": merged,
            })

    if only:
        add_combo(only)
    else:
        add_combo(["bypass-license", "shell", "integrity"])
        add_combo(["trace", "api", "token", "integrity"])
        for c in CAP_ORDER:
            for partner in SYNERGY.get(c, ()):
                if c < partner:
                    add_combo([c, partner])
    return combos


def render_combo_report(combos, total_patches):
    """Ket xuat bao cao combo dang Markdown."""
    lines = ["# Bao cao gop combo", "",
             "- Tong patch dau vao: %d" % total_patches,
             "- So combo tao duoc: %d" % len(combos), ""]
    for cb in combos:
        lines.append("## %s" % cb["label"])
        lines.append("- File: `%s`" % cb["file"])
        lines.append("- So khối: %d | Xung dot tach: %d" % (
            cb["sections"], cb["conflicts"]))
        lines.append("- Nguon (%d patch):" % len(cb["patches"]))
        for n in cb["patches"]:
            lines.append("  - %s" % n)
        lines.append("")
    return "\n".join(lines)
