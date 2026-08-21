# -*- coding: utf-8 -*-
"""Bo toi uu: gop/dedupe/phat hien xung dot va ket xuat patch chuan."""

import collections
import hashlib
import re

from .model import Patch, Section
from .parser import parse_text


def fingerprint_section(sec):
    """Van tay cua mot khối lệnh — dung de gop trung lap."""
    parts = [sec.type]
    for key in ("NAME", "TARGET", "MATCH", "REGEX", "DOTALL", "REPLACE",
                "ASSIGN", "GOTO", "SOURCE", "EXTRACT", "SCRIPT",
                "SMALI_NEEDED", "MAIN_CLASS", "ENTRANCE", "PARAM",
                "VALUE", "CODE", "METHOD", "ENTRY", "TAG", "BEFORE",
                "AFTER", "CONFIG_URL"):
        parts.append(sec.get(key))
    h = hashlib.sha1()
    for part in parts:
        h.update(part.encode("utf-8", "replace"))
    return h.hexdigest()


def dedupe_sections(patch):
    """Bo cac khối trung lap (giu khối xuat hien dau tien)."""
    seen = set()
    kept = []
    removed = 0
    for sec in patch.sections:
        fp = fingerprint_section(sec)
        if fp in seen:
            removed += 1
            continue
        seen.add(fp)
        kept.append(sec)
    return kept, removed


def find_conflicts(patches):
    """Tim xung dot: cung TARGET+MATCH+REGEX nhung khac REPLACE."""
    groups = collections.defaultdict(list)
    for p in patches:
        for sec in p.sections:
            if sec.type == "MATCH_REPLACE":
                key = (sec.get("TARGET").strip(), sec.get("MATCH"),
                       sec.get("REGEX").strip().lower())
                groups[key].append((p.name, sec.get("REPLACE")))
            elif sec.type == "ADD_FILES":
                # Cung TARGET nhung khac SOURCE/noi dung -> xung dot
                # (patch sau bi bo qua vi file da ton tai)
                source = sec.get("SOURCE").strip()
                data = p.assets.get(source) if source else None
                digest = hashlib.sha1(data).hexdigest()[:10] if data else "?"
                key = ("ADD_FILES", sec.get("TARGET").strip())
                groups[key].append((p.name, source + "@" + digest))
    conflicts = []
    for key, items in groups.items():
        distinct = set(repl for _, repl in items)
        if len(distinct) > 1:
            conflicts.append({
                "target": key[0],
                "patches": sorted(set(name for name, _ in items)),
                "variants": len(distinct),
            })
    return conflicts


def render_patch_text(patch, header=None):
    """Ket xuat patch.txt chuan: metadata, khoa viet hoa, moi khối co the dong."""
    out = []
    if header:
        out.append("# " + header.replace("\n", "\n# "))
        out.append("")
    if patch.min_engine_ver:
        out += ["[MIN_ENGINE_VER]", patch.min_engine_ver.strip(), ""]
    if patch.author:
        out += ["[AUTHOR]", patch.author.strip(), ""]
    if patch.package:
        out += ["[PACKAGE]", patch.package.strip(), ""]
    for sec in patch.sections:
        if sec.type in ("MIN_ENGINE_VER", "AUTHOR", "PACKAGE"):
            continue
        out.append("[%s]" % sec.type)
        for key, value in sec.body.items():
            out.append("%s:" % key)
            if value:
                lines = value.split("\n")
                if lines[0].strip():
                    out.append("    " + lines[0])
                else:
                    out.append(lines[0])
                out.extend(lines[1:])
        out.append("[/%s]" % sec.type)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def rebuild_patch(patch, header=None):
    """Tao Patch moi tu noi dung chuan hoa (giu metadata va tai nguyen)."""
    text = render_patch_text(patch, header=header)
    new_patch = parse_text(text)
    new_patch.source = patch.source
    new_patch.assets = patch.assets
    new_patch.asset_root = patch.asset_root
    new_patch.min_engine_ver = patch.min_engine_ver
    new_patch.author = patch.author
    new_patch.package = patch.package
    return new_patch


def cluster_tag(name):
    """Gan nhan nhóm cho patch dua tren tên — phuc vu gop toi uu."""
    n = name.lower()
    groups = [
        (("androidid", "android_id", "device", "imei", "serial", "sernum",
          "mac", "bssid", "brand", "wifi", "bluetooth", "imei_locker"),
         "Spoof-ID"),
        (("internet", "disconnect", "noplaygames", "nowifi", "nolocation"),
         "Mang"),
        (("save",), "Luu-tru"),
        (("modguard", "hide", "anti-", "root", "ref_logging"), "Chong-phat-hien"),
        (("install", "unpack", "dexextractor", "logcat", "receiver",
          "font", "fullscreen", "dpi", "icon", "update", "autoboot",
          "camera", "audio", "time", "duplicate", "tool", "package_name",
          "minsdk", "patch_", "dppp", "entrance"), "Tien-ich"),
    ]
    for keys, tag in groups:
        if any(k in n for k in keys):
            return tag
    return "Khac"


def component_targets(patches):
    """Tap hop target cua mot nhóm patch (dung do do tuong dong)."""
    out = set()
    for p in patches:
        for s in p.sections:
            t = s.get("TARGET").strip()
            if t:
                out.add(t)
    return out


def _match_set(patches):
    out = set()
    for p in patches:
        for s in p.sections:
            m = s.get("MATCH").strip()
            if m:
                out.add(m)
    return out


def target_similarity(patches_a, patches_b):
    """Do tuong dong giua hai nhóm patch.

    Ket hop Jaccard cua TARGET (60%) va cua chuoi MATCH (40%) — chi coi la
    "giong nhau" khi ca hai cung huong toi mức tieu va cung xu ly chuoi.
    """
    ta = component_targets(patches_a)
    tb = component_targets(patches_b)
    if not ta or not tb:
        return 0.0
    jac_t = len(ta & tb) / len(ta | tb)
    ma = _match_set(patches_a)
    mb = _match_set(patches_b)
    jac_m = (len(ma & mb) / len(ma | mb)) if (ma and mb) else 0.0
    return 0.6 * jac_t + 0.4 * jac_m


def merge_patches(patches, tag):
    """Gop mot nhóm patch thanh mot patch duy nhat (khong trung lap).

    Khi gop nhieu patch, nhan GOTO/NAME duoc đạt tien to theo tung patch
    (p0_, p1_, ...) de cac luong GOTO khong dung nhau.
    """
    engine_vers = []
    authors = []
    packages = []
    sections = []
    seen = set()
    multi = len(patches) > 1
    for idx, p in enumerate(patches):
        if p.min_engine_ver:
            try:
                engine_vers.append(int(p.min_engine_ver))
            except ValueError:
                pass
        if p.author:
            authors.append(p.author.strip())
        if p.package:
            packages.append(p.package.strip())
        labels_map = {}
        prefix = "p%d_" % idx if multi else ""
        for sec in p.sections:
            if sec.name:
                labels_map[sec.name] = prefix + sec.name
        for sec in p.sections:
            if sec.type in ("MIN_ENGINE_VER", "AUTHOR", "PACKAGE"):
                continue
            body = dict(sec.body)
            if multi:
                if sec.type in ("GOTO", "MATCH_GOTO") and body.get("GOTO"):
                    g = body["GOTO"].strip()
                    body["GOTO"] = labels_map.get(g, g)
                if sec.name:
                    body["NAME"] = labels_map[sec.name]
            new_sec = Section(type=sec.type, body=body, order=len(sections),
                              closed=sec.closed,
                              name=labels_map.get(sec.name, sec.name))
            fp = fingerprint_section(new_sec)
            if fp in seen:
                continue
            seen.add(fp)
            sections.append(new_sec)
    merged = Patch(source="<gop:%s>" % tag)
    merged.min_engine_ver = str(max(engine_vers)) if engine_vers else "2"
    merged.author = authors[0] if authors else "patchx"
    merged.package = "*" if "*" in packages else (packages[0] if packages else "*")
    merged.sections = sections
    return merged


# ---- Nhan dien nang luc cua patch (de gop combo ho tro nhau) ----
CAPABILITY_RULES = [
    ("bypass-license", ("bypass", "license", "vip", "premium", "hack", "crack",
                        "activator", "ispremium", "auth_vk", "accounts")),
    ("purchase", ("purchase", "iap", "billing", "buy", "in-app", "mua-hang",
                  "mua hang")),
    ("shell", ("shell", "mod", "hook", "frida", "gadget", "inject", "dex",
               "script", "entrance")),
    ("token", ("token", "oauth", "session", "quet-token", "scan-token")),
    ("api", ("api", "endpoint", "url", "retrofit", "okhttp")),
    ("trace", ("trace", "logcat", "logging", "debug", "dump", "flow", "stream",
               "ref_logging", "truy-vet")),
    ("integrity", ("integrity", "signature", "sigcheck", "verify", "xac minh",
                   "toan ven", "bypass_sig", "bin_sig")),
    ("google", ("google", "gms", "play", "gservices")),
    ("root-hide", ("root", "rootbeer", "magisk", "root-hide", "an root")),
    ("ssl-pinning", ("pinning", "ssl", "certificate", "x509", "trustmanager",
                     "pin")),
    ("anti-debug", ("debug", "antidebug", "tracerpid", "go lỗi", "debugger")),
    ("frida-hide", ("frida", "frida-detect", "gum-js", "checkfrida")),
    ("emulator", ("emulator", "goldfish", "genymotion", "may ao", "blue-stack",
                  "bluestacks")),
    ("ads", ("ads", "advert", "banner", "quang cao", "reklama", "remove_ads")),
    ("id-spoof", ("android_id", "androidid", "device_id", "deviceid",
                  "imei", "serial", "serialno", "bssid", "bluetooth",
                  "wifi_mac", "mac", "spoof-id")),
    ("anonymity", ("anonymous", "anonymity", "fake", "gps", "location",
                   "mock", "an danh", "hide", "nointernet", "nowifi",
                   "noplaygames", "privacy")),
    ("permission", ("permission", "quyen", "camera", "recordaudio", "sms",
                    "contact", "calendar", "phone")),
    ("network", ("internet", "network", "wifi", "mang", "disconnect")),
    ("ui", ("theme", "splash", "toast", "dialog", "icon", "orientation",
            "fullscreen", "giao dien", "dark")),
    ("save", ("save", "luu", "data_editor", "mem_editor", "duplicate")),
    ("installer", ("install", "package", "minsdk", "unpack", "dppp")),
    ("font", ("font", "my_font")),
]

CONTENT_SIGNALS = {
    "integrity": ("signature", "sigcheck", "checksignature", "verifysign"),
    "google": ("google", "gms", "play.google"),
    "bypass-license": ("license", "premium", "ispremium", "billing", "activator"),
    "purchase": ("getbuysintent", "launchbillingflow", "querypurchases",
                 "getskudetails", "billingclient", "com.android.vending.billing"),
    "shell": ("frida", "libfrida-gadget", "script.dex", "smali.zip", "main_class"),
    "root-hide": ("isrooted", "rootbeer", "checkforroot", "findbinary",
                  "magisk", "issu", "checkrooted"),
    "ssl-pinning": ("checkservertrusted", "certificatệpinner",
                    "x509trustmanager", "sslcontext", "trustmanager"),
    "anti-debug": ("isdebuggerconnected", "tracerpid", "antidebug", "ptrace"),
    "frida-hide": ("frida", "gum-js-loop", "checkfrida", "findfrida",
                   "frida-server"),
    "emulator": ("isemulator", "goldfish", "genymotion", "build.fingerprint",
                 "checkemulator", "blue-stack"),
    "trace": ("logcat", "debug", "trace", "dump"),
    "token": ("token", "oauth", "sessionid", "bearer", "authorization",
              "api_key", "secret"),
    "api": ("http://", "https://", "lầndroid/net/", "ljava/net/url",
            "lokhttp3", "lretrofit2", "api/"),
    "installer": ("installerpackagename", "getinstallerpackagename"),
    "ads": ("ca-app-pub", "doubleclick", "googleads", "advert"),
}


def patch_capabilities(patch):
    """Nhan dien nang luc cua patch tu tên + noi dung khối lệnh."""
    name = (patch.name or "").lower()
    text = " ".join(s.get("MATCH") + " " + s.get("REPLACE") + " "
                    + s.get("TARGET") + " " + s.get("SOURCE") + " "
                    + s.get("CODE") + " " + s.get("VALUE") + " "
                    + s.get("METHOD") + " " + s.get("CONFIG_URL")
                    for s in patch.sections).lower()
    caps = set()
    for cap, keys in CAPABILITY_RULES:
        if any(k in name for k in keys):
            caps.add(cap)
    for cap, signals in CONTENT_SIGNALS.items():
        if any(sig in text for sig in signals):
            caps.add(cap)
    for s in patch.sections:
        if s.type == "HOOK_SCRIPT":
            caps.add("shell")
        elif s.type in ("TRACE", "API_LOG"):
            caps.add("trace")
        elif s.type == "REMOTE_CONFIG":
            caps.add("api")
    return caps


CAP_LABELS = {
    "bypass-license": "Bypass-VIP/License",
    "purchase": "Gia-Lap-Mua-Hang",
    "shell": "Mod-Shell",
    "token": "Quet-Token",
    "api": "Tim-API",
    "trace": "Truy-Vet-Du-Lieu",
    "integrity": "Check-Toan-Ven",
    "google": "Bypass-Google",
    "root-hide": "An-Root/Gia-Lap",
    "ssl-pinning": "Go-SSL-Pinning",
    "anti-debug": "Chong-Debug",
    "frida-hide": "An-Frida",
    "emulator": "Bo-Kiem-Tra-May-Ao",
    "ads": "Chan-Quang-Cao",
    "id-spoof": "Spoof-ID",
    "anonymity": "An-Danh",
    "permission": "Quyen",
    "network": "Mang",
    "ui": "Giao-Dien",
    "save": "Luu-Tru",
    "installer": "Cai-Dat",
    "font": "Font",
}

CAP_ORDER = ["bypass-license", "purchase", "shell", "integrity", "google",
             "root-hide", "ssl-pinning", "anti-debug", "emulator", "token",
             "api", "trace", "ads", "id-spoof", "anonymity", "permission",
             "network", "ui",
             "save", "installer", "font"]

SYNERGY = {
    "bypass-license": ("shell", "integrity", "google", "token"),
    "purchase": ("bypass-license", "integrity"),
    "shell": ("bypass-license", "integrity", "token", "trace"),
    "integrity": ("bypass-license", "google", "shell"),
    "google": ("bypass-license", "integrity"),
    "root-hide": ("integrity", "anti-debug", "emulator"),
    "ssl-pinning": ("network", "api", "token"),
    "anti-debug": ("root-hide", "integrity", "emulator"),
    "frida-hide": ("root-hide", "anti-debug", "shell"),
    "emulator": ("root-hide", "anti-debug"),
    "token": ("shell", "trace", "api"),
    "api": ("trace", "token", "shell"),
    "trace": ("token", "api", "shell"),
    "ads": ("anonymity", "network"),
    "id-spoof": ("anonymity", "network"),
    "anonymity": ("network", "ads", "id-spoof"),
    "permission": ("anonymity",),
    "network": ("ads", "anonymity", "id-spoof"),
    "ui": (),
    "save": (),
    "installer": ("shell",),
    "font": (),
}
