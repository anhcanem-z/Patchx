# -*- coding: utf-8 -*-
"""Quan ly phien chay patch do nguoi dung chon.

Cung cap:
  - danh sach patch theo kha nang;
  - goi y combo bo tro nhau dua tren SYNERGY va nang luc patch;
  - chon patch de chay chung mot phien.
"""

import os

from .parser import parse_patch_file
from .audit import parse_nested_zip
from .optimizer import (CAP_LABELS, CAP_ORDER, SYNERGY, merge_patches,
                        patch_capabilities, find_conflicts)


def load_patch_map(root):
    """Nap toan bo patch tu thu mức; tra dict tên -> Patch."""
    patches = {}
    if not os.path.isdir(root):
        return patches
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith(".zip"):
            continue
        path = os.path.join(root, name)
        try:
            p = parse_patch_file(path)
            patches[p.name or os.path.splitext(name)[0]] = p
        except ValueError:
            nested = parse_nested_zip(path)
            for idx, p in enumerate(nested):
                key = p.name or os.path.splitext(name)[0]
                if len(nested) > 1:
                    key = "%s#%d" % (os.path.splitext(name)[0], idx + 1)
                patches[key] = p
        except Exception:
            continue
    return patches


def capability_groups(patches):
    """Chia patch theo tung kha nang; patch co the thuoc nhieu nhóm."""
    groups = {}
    for name, p in patches.items():
        caps = patch_capabilities(p)
        if not caps:
            caps = {"khac"}
        for cap in caps:
            groups.setdefault(cap, []).append(name)
    ordered = []
    for cap in CAP_ORDER:
        if cap in groups:
            ordered.append((cap, sorted(groups.pop(cap))))
    for cap in sorted(groups):
        ordered.append((cap, sorted(groups[cap])))
    return ordered


def complementary_combos(patches, max_combos=120):
    """Goi y cac combo patch bo tro nhau (co nang luc nam trong SYNERGY)."""
    caps_of = {}
    for name, p in patches.items():
        caps_of[name] = patch_capabilities(p)
    combos = []
    names = sorted(caps_of)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ca = caps_of[a]
            cb = caps_of[b]
            support = set()
            for c in ca:
                for d in cb:
                    if d in SYNERGY.get(c, ()) or c in SYNERGY.get(d, ()):
                        support.add((c, d))
            if support:
                combos.append({
                    "patches": [a, b],
                    "capabilities": sorted(ca | cb),
                    "support": sorted(support),
                })
            if len(combos) >= max_combos:
                return combos
    return combos


def resolve_patch_names(patches, raw_names):
    """Chuyen danh sach tên do nguoi dung nhap thanh danh sach patch."""
    wanted = [x.strip() for x in raw_names.split(",") if x.strip()]
    selected = []
    missing = []
    for w in wanted:
        if w in patches:
            selected.append(patches[w])
            continue
        # Tim theo tên khong co .zip, khong phan biet hoa/thuong
        match = None
        for name in patches:
            base = os.path.splitext(name)[0]
            if base.lower() == w.lower():
                match = patches[name]
                break
        if match is None:
            # Tim chuoi con gan dung
            candidates = [n for n in patches if w.lower() in n.lower()]
            if len(candidates) == 1:
                match = patches[candidates[0]]
        if match is not None:
            selected.append(match)
        else:
            missing.append(w)
    return selected, missing


def merge_selected(selected, tag="phien"):
    """Gop cac patch da chon thanh mot patch phien duy nhat."""
    if not selected:
        return None
    return merge_patches(selected, tag)
