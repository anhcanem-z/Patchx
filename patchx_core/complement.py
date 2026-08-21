# -*- coding: utf-8 -*-
"""Tu phat hien cac patch bo tro cho nhau — phien ban 2 (gop theo ho thuc te).

Thiet ke moi (sau khi danh gia phien ban 1 khong hieu qua):
  1. GOP THEO HO: moi patch duoc xep vao cac ho chuc nang HEP (ads, id-spoof,
     license, shell, toan ven, google, theme, splash, toast, screen, mang,
     an danh, luu tru, quyen, cai đạt). Cac patch cung ho gop thanh combo,
     xung dot tu tach. KHONG gop cheo ho qua chuoi nang luc.
  2. BO TRO CLASS-LINK: patch CUNG CAP class (ADD_FILES/asset .smali) ma patch
     khac DUNG (MATCH/REPLACE) -> combo bo tro, kem bang chung class.
  3. Patch khong thuoc ho nao va khong co class-link -> liet ke co lap.

Ket qua: combo that su co y nghia (cung mức tieu), khong bi tron lần.
"""

import re

from .optimizer import merge_patches, find_conflicts
from .parser import parse_patch_file

CLASS_RE = re.compile(r"L([a-zA-Z0-9_/$]+);")
SMALI_CLASS_RE = re.compile(r"\.class\s+(?:[a-z]+\s+)*L([a-zA-Z0-9_/$]+);")
FRAMEWORK_PREFIXES = ("Landroid/", "Ljava/", "Ldalvik/", "Lkotlin/", "Lorg/",
                      "Ljunit/", "Lcom/google/android/", "Lcom/google/firebase/",
                      "Lcom/google/gms/", "Landroidx/")

# Ho chuc nang hep — tu khoa tên patch (khong gop cheo ho)
FAMILY_RULES = [
    ("ads", ("ads", "advert", "banner", "reklama", "remove_ads",
             "antiqueclam", "anti-ads", "anti-advertising")),
    ("id-spoof", ("androidid", "android_id", "deviceid", "device_id", "imei",
                  "serial", "serialno", "bssid", "bluetooth", "wifi_mac",
                  "mac_address", "spoof-id", "sernum", "brand")),
    ("license", ("license", "vip", "premium", "activator", "ispremium",
                 "accounts_hack", "auth_vk", "billing")),
    ("signature", ("signature", "sigcheck", "bin_sig", "bypass_sig",
                   "signaturehack")),
    ("google", ("google", "gms", "gservices", "play")),
    ("shell", ("shell", "frida", "gadget", "dex", "script", "entrance",
               "hook", "inject")),
    ("token", ("token", "oauth", "session")),
    ("api", ("api", "endpoint", "retrofit", "okhttp")),
    ("trace", ("trace", "logcat", "logging", "debug", "dump", "flow",
               "ref_logging")),
    ("mang", ("internet", "wifi", "disconnect", "nowifi", "noplaygames")),
    ("an danh", ("anonymous", "anonymity", "fake", "gps", "mock", "location",
                 "nointernet", "hide", "privacy", "an danh")),
    ("quyen", ("permission", "camera", "recordaudio", "sms", "contact",
               "calendar", "phone", "memory")),
    ("luu tru", ("save", "data_editor", "mem_editor", "duplicate")),
    ("theme", ("theme", "dark", "holo", "material", "appcompat")),
    ("splash", ("splash",)),
    ("toast", ("toast", "dialog", "notify", "alert")),
    ("screen", ("fullscreen", "orientation", "dpi", "portrait", "lầndscape")),
    ("cai đạt", ("install", "minsdk", "unpack", "package", "dppp")),
    ("font", ("font",)),
]

FAM_LABELS = {f: f for f, _ in FAMILY_RULES}


def patch_families(patch):
    """Ho chuc nang cua patch — tu tên + noi dung khối lệnh."""
    name = (patch.name or "").lower()
    text = " ".join(s.get("MATCH") + " " + s.get("REPLACE") + " "
                    + s.get("TARGET") + " " + s.get("SOURCE")
                    for s in patch.sections).lower()
    fams = set()
    for fam, keys in FAMILY_RULES:
        if any(k in name for k in keys):
            fams.add(fam)
        elif fam == "token" and any(k in text for k in
                                    ("token", "oauth", "bearer", "sessionid")):
            fams.add(fam)
        elif fam == "api" and any(k in text for k in
                                  ("http://", "https://", "lầndroid/net/",
                                   "lokhttp3", "lretrofit2")):
            fams.add(fam)
        elif fam == "trace" and any(k in text for k in
                                    ("logcat", "debug", "trace", "dump")):
            fams.add(fam)
        elif fam == "signature" and any(k in text for k in
                                        ("signature", "sigcheck",
                                         "verifysign")):
            fams.add(fam)
        elif fam == "ads" and any(k in text for k in
                                  ("ca-app-pub", "doubleclick", "googleads")):
            fams.add(fam)
        elif fam == "google" and any(k in text for k in
                                     ("play.google", "com.google.android.gms")):
            fams.add(fam)
    return fams


def provides(patch):
    """Class ma patch CUNG CAP (tu ADD_FILES/asset .smali)."""
    out = set()
    for sec in patch.sections:
        if sec.type == "ADD_FILES":
            target = sec.get("TARGET").strip()
            if target.endswith(".smali"):
                cls = target[:-6].split("smali/", 1)[-1]
                out.add("L" + cls + ";")
    for name, data in patch.assets.items():
        if name.endswith(".smali"):
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                continue
            m = SMALI_CLASS_RE.search(text)
            if m:
                out.add("L" + m.group(1) + ";")
    return out


def uses(patch):
    """Class ma patch DUNG (MATCH/REPLACE/TARGET), bo class framework."""
    out = set()
    for sec in patch.sections:
        for key in ("MATCH", "REPLACE", "TARGET"):
            for m in CLASS_RE.finditer(sec.get(key, "").replace("\n", " ")):
                full = "L" + m.group(1) + ";"
                if not full.startswith(FRAMEWORK_PREFIXES):
                    out.add(full)
    return out


def class_links(patches):
    """Canh class-link: A cung cap class ma B dung (kem bang chung)."""
    info = {}
    for p in patches:
        info[p.name] = (provides(p), uses(p))
    links = []
    names = [p.name for p in patches]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pa, ua = info[names[i]]
            pb, ub = info[names[j]]
            inter = (pa & ub) | (pb & ua)
            if inter:
                links.append({
                    "a": names[i], "b": names[j],
                    "classes": sorted(inter),
                })
    return links


def _pack_safe(patches):
    """Goi cac patch khong xung dot vao cung nhóm; xung dot tach rieng."""
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


def discover_combos(patches):
    """Phien ban 2: gop theo ho + class-link, khong gop cheo ho qua nang luc."""
    # Buoc 1: gom patch theo ho
    family_members = {}
    for p in patches:
        for f in patch_families(p):
            family_members.setdefault(f, []).append(p)

    used_pos = set()
    combos = []

    def emit(label, pack, fam, kind):
        merged = merge_patches(pack, label)
        suffix = "" if len(pack) == 1 else ""
        combos.append({
            "label": label,
            "file": label.replace("/", "-") + ".patch",
            "patches": [p.name for p in pack],
            "sections": len(merged.sections),
            "kind": kind,
            "merged": merged,
        })

    # Combo theo ho (chi khi >= 2 patch)
    for fam, members in sorted(family_members.items()):
        packs, _ = _pack_safe(members)
        for pi, pack in enumerate(packs):
            if len(pack) < 2:
                continue
            label = fam if len(packs) == 1 else "%s_%d" % (fam, pi + 1)
            emit(label, pack, fam, "ho")
            for p in pack:
                for i, q in enumerate(patches):
                    if q is p:
                        used_pos.add(i)

    # Buoc 2: class-link cho cac patch CHUA vao ho (bo tro that)
    free = [p for i, p in enumerate(patches) if i not in used_pos]
    if free:
        # do thi class-link
        pos = {}
        for i, p in enumerate(free):
            pos.setdefault(p.name, []).append(i)
        parent = list(range(len(free)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        links = class_links(free)
        for e in links:
            for ia in pos.get(e["a"], []):
                for ib in pos.get(e["b"], []):
                    union(ia, ib)
        comps = {}
        for i, p in enumerate(free):
            comps.setdefault(find(i), []).append(p)
        for comp in sorted(comps.values(), key=len, reverse=True):
            if len(comp) < 2:
                continue
            packs, _ = _pack_safe(comp)
            comp_links = [e for e in links
                          if e["a"] in {p.name for p in comp}
                          and e["b"] in {p.name for p in comp}]
            for pi, pack in enumerate(packs):
                if len(pack) < 2:
                    continue
                label = "Bo-tro-Class" if len(packs) == 1 else \
                    "Bo-tro-Class_%d" % (pi + 1)
                merged = merge_patches(pack, label)
                combos.append({
                    "label": label,
                    "file": label + ".patch",
                    "patches": [p.name for p in pack],
                    "sections": len(merged.sections),
                    "kind": "class-link",
                    "links": comp_links,
                    "merged": merged,
                })
                for p in pack:
                    for i, q in enumerate(patches):
                        if q is p:
                            used_pos.add(i)

    isolated = [p.name for i, p in enumerate(patches) if i not in used_pos]
    return combos, isolated


def render_auto_report(combos, isolated, total):
    """Ket xuat bao cao combo tu phat hien."""
    lines = ["# Bao cao combo tu phat hien (bo tro cho nhau) — v2", "",
             "- Tong patch dau vao: %d" % total,
             "- Combo tao duoc: %d" % len(combos),
             "- Patch co lap: %d" % len(isolated), ""]
    for cb in combos:
        lines.append("## %s" % cb["label"])
        lines.append("- So khối: %d | Loai: %s" % (cb["sections"],
                                                   cb["kind"]))
        lines.append("- Nguon (%d patch):" % len(cb["patches"]))
        for n in cb["patches"]:
            lines.append("  - %s" % n)
        if cb.get("links"):
            lines.append("- Class-link:")
            for e in cb["links"][:10]:
                lines.append("  - %s <-> %s: %s" % (
                    e["a"], e["b"], ", ".join(e["classes"])))
        lines.append("")
    if isolated:
        lines.append("## Patch co lap (chua tim thay bo tro)")
        lines.append(", ".join(sorted(isolated)))
        lines.append("")
    return "\n".join(lines)
