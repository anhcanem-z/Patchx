# -*- coding: utf-8 -*-
"""Bypass Advisor — phan tich du lieu quet APK thanh bao cao trien khai.

Nhan ket qua coverage (da quet) + cache noi dung cây APK, sinh:
  - danh sach điểm bypass cu the (tệp, khối, so khớp, bien the mo rong);
  - cach lam va cong cu cho tung nang luc patch;
  - cac lop bao ve phat hien duoc trong APK (root, SafetyNet, pinning, ...);
  - phuong an trien khai tung buoc + de xuat tang kha nang thanh cong;
  - uoc luong ty le thanh cong (%).

Moi thong bao bang tieng Viet; chuoi ky thuat giu nguyen goc.
"""

import re

# --- Uu tien nang luc (cang kho/gia tri cang cao) ---
CAP_PRIORITY = {
    "bypass-license": 1.00, "integrity": 0.95, "google": 0.90,
    "purchase": 0.88, "token": 0.85, "api": 0.80, "trace": 0.75,
    "shell": 0.70, "ssl-pinning": 0.68, "root-hide": 0.65,
    "anonymity": 0.60, "anti-debug": 0.57, "frida-hide": 0.56,
    "id-spoof": 0.55, "ads": 0.50, "network": 0.45, "emulator": 0.42,
    "permission": 0.35,
    "installer": 0.30, "save": 0.25, "ui": 0.20, "font": 0.10,
}

# --- Cach lam + cong cu theo nang luc ---
CAP_TOOLING = {
    "bypass-license": {
        "cach": "Vo hieu hoa kiem tra VIP/license: gan co da mua bang SET_BOOL, "
                "nhay qua khối kiem tra bang MATCH_GOTO, hoac hook ham kiem tra "
                "bang Frida/LSPosed.",
        "cong_cu": ["patchx apply", "apktool", "apksigner", "Frida", "LSPosed"],
        "xac_minh": "Mo tinh nang VIP; xem logcat tim log trang thai license.",
    },
    "purchase": {
        "cach": "Gia lap mua hang trong app: vo hieu hoa lỗi goi "
                "queryPurchases/getBuyIntênt (MATCH_REPLACE), hoac tra trang "
                "thai da mua qua SET_BOOL/MATCH_ASSIGN nhu Lucky Patcher.",
        "cong_cu": ["patchx apply", "apktool", "Lucky Patcher"],
        "xac_minh": "Bam mua trong app va xac nhan thanh cong khong tru tien.",
    },
    "integrity": {
        "cach": "Vo hieu hoa kiem tra toan ven/chu ky: sua luong check (MATCH_GOTO) "
                "hoac tra true/false co dinh (SET_BOOL/MATCH_ASSIGN).",
        "cong_cu": ["patchx apply", "apktool", "apksigner"],
        "xac_minh": "Xoa bao lỗi 'signature mismatch'/'app modified' khi mo ung dung.",
    },
    "google": {
        "cach": "Bo kiem tra Google Play Services/SafetyNet: go hoac bo qua khối "
                "attestation, thay bang ket qua gia.",
        "cong_cu": ["patchx apply", "apktool", "LSPosed"],
        "xac_minh": "Mo ung dung khi khong co Google Play day du; kiem tra logcat.",
    },
    "root-hide": {
        "cach": "Vo hieu hoa kiem tra root: comment lỗi goi isRooted/RootBeer "
                "va gan ket qua false (MATCH_REPLACE), hoac hook ham kiem tra "
                "bang Frida/Magisk DenyList.",
        "cong_cu": ["patchx apply", "apktool", "Frida", "Magisk"],
        "xac_minh": "Mo app tren may da root, xac nhan khong bi chan.",
    },
    "ssl-pinning": {
        "cach": "Bo khoa chung chi: comment lỗi goi checkServerTrusted trong "
                "X509TrustManager hoac vo hieu hoa CertificatePinner, sau do "
                "dung proxy (mitmproxy/Charles) bat goi.",
        "cong_cu": ["patchx apply", "apktool", "Frida", "objection",
                    "mitmproxy"],
        "xac_minh": "Bat duoc HTTPS qua proxy khong bao lỗi chung chi.",
    },
    "anti-debug": {
        "cach": "Chong phat hien go lỗi: gan ket qua isDebuggerConnected ve "
                "false, xoa kiem tra TracerPid bang MATCH_REPLACE/SET_BOOL.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Chay app trong trinh go lỗi ma khong tu thoat.",
    },
    "frida-hide": {
        "cach": "An dau vet Frida: thay chuoi 'frida' bang gia tri gia, comment "
                "lỗi goi checkFrida/findFrida, tranh phat hien gadget.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Mo app khi co Frida trong bo nho, xac nhan khong bi chan.",
    },
    "emulator": {
        "cach": "Bo kiem tra may ao: gan ket qua isEmulator/findBinary ve "
                "false, sua Build.FINGERPRINT tra ve thiet bi that.",
        "cong_cu": ["patchx apply", "apktool", "Frida"],
        "xac_minh": "Mo app tren may ao, xac nhan khong bi chan.",
    },
    "token": {
        "cach": "Quet va vo hieu hoa endpoint lay token: chan MATCH_REPLACE chuoi "
                "token/khoa, thay bang chuoi gia hoac hook tra token hop le.",
        "cong_cu": ["patchx apply", "Frida", "logcat", "tcpdump"],
        "xac_minh": "Bat mang (tcpdump/Frida) xem token gui di sau khi patch.",
    },
    "api": {
        "cach": "Tim API that bang log API_LOG/TRACE, sau do thay domain/endpoint "
                "trong MATCH_REPLACE hoac chan tai class xu ly mang.",
        "cong_cu": ["patchx apply", "Frida", "logcat"],
        "xac_minh": "Theo doi log chua endpoint sau khi kich hoat chuc nang.",
    },
    "trace": {
        "cach": "Bat truy vet du lieu: chen TRACE/API_LOG vao method mức tieu de "
                "doc tham so va phan hoi trước khi quyet dinh patch.",
        "cong_cu": ["patchx apply", "logcat"],
        "xac_minh": "Doc logcat thay du lieu mong muon in ra.",
    },
    "shell": {
        "cach": "Chen khối tao mod qua INIT/HOOK_SCRIPT: chay lệnh/script khi app "
                "mo de bom bien hoac goi ham noi bo.",
        "cong_cu": ["patchx apply", "apktool", "Frida"],
        "xac_minh": "Kiem tra hieu luc mod ngay sau khi app khối dong.",
    },
    "ads": {
        "cach": "Chan quang cao: thay URL ad network bang chuoi rong hoac bo qua "
                "khối hien thi quang cao.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Chay app va xac nhan khong con banner/interstitial.",
    },
    "id-spoof": {
        "cach": "Gia mao ID thiet bi: sua MATCH_REPLACE chuoi tra ve device id, "
                "hoac hook ham lay ID bang Frida.",
        "cong_cu": ["patchx apply", "Frida"],
        "xac_minh": "Doi chieu ID app doc duoc sau khi patch.",
    },
    "anonymity": {
        "cach": "An danh: vo hieu hoa thu thap dinh danh (analytics), thay chuoi "
                "identifiers bang gia tri gia.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Xem log/bat mang khong con du lieu dinh danh that.",
    },
    "permission": {
        "cach": "Dieu chinh quyen: sua AndroidManifest.xml (them/bot quyen, "
                "debuggable, backup).",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Cai APK, kiem tra danh sach quyen hien thi.",
    },
    "network": {
        "cach": "Dieu khien mang: chan/go gioi han mang hoac thay endpoint bang "
                "server gia lap.",
        "cong_cu": ["patchx apply", "Frida", "tcpdump"],
        "xac_minh": "Bat mang xac nhan request den endpoint mong muon.",
    },
    "installer": {
        "cach": "Bo kiem tra nguon cai đạt: sua luong kiem tra installer "
                "(getInstallerPackageName) tra ve gia tri hop le.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Mo app ngay sau khi cai tu file APK.",
    },
    "save": {
        "cach": "Go gioi han luu tru: bo khoa tinh nang luu, thay dieu kien "
                "tra true (SET_BOOL) hoac bo qua khối gioi han.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Thu luu/nang cap trong app.",
    },
    "ui": {
        "cach": "Dieu chinh giao dien: sua van ban/mau/bo cuc trong res/XML.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Mo app xac nhan thay doi hien thi.",
    },
    "font": {
        "cach": "Thay font chu trong res/font.",
        "cong_cu": ["patchx apply", "apktool"],
        "xac_minh": "Mo app xac nhan font moi.",
    },
}

# --- Dau hieu lop bao ve trong APK (quet nhanh tren noi dung da doc) ---
PROTECTION_PATTERNS = [
    ("root", ["isRooted", "RootBeer", "checkForRoot", "findBinary",
              "DetectRoot", "RootCheck", "su -c"]),
    ("safetynet", ["SafetyNet", "PlayIntegrity", "attestation",
                   "DeviceCheck", "integrity verdict"]),
    ("frida", ["frida", "gum-js-loop", "frida-server", "checkFrida",
               "findFrida", "ioctl", "ptrace"]),
    ("signature", ["checkSignature", "signature check", "checkSigning",
                   "PackageManager.SIGNATURE"]),
    ("anti-debug", ["isDebuggerConnected", "anti-debug", "Debug.isDebugger",
                    "TracerPid"]),
    ("pinning", ["CertificatePinner", "ssl pinning", "X509TrustManager",
                 "checkServerTrusted"]),
    ("emulator", ["isEmulator", "goldfish", "generic", "Genymotion",
                  "Build.FINGERPRINT"]),
    ("root-hide", ["Magisk", "hide root", "detect magisk", "SafetyNet",
                   "ctsProfileMatch"]),
    ("tamper", ["getPackageInfo", "ApplicationInfo.FLAG_DEBUGGABLE",
                "checkIntSig", "verifySignature"]),
]
# Muc phat (% điểm) cho moi lop bao ve xuat hien
PROTECTION_PENALTY = {
    "root": 12.0, "safetynet": 18.0, "signature": 20.0,
    "anti-debug": 10.0, "pinning": 15.0, "emulator": 8.0, "root-hide": 10.0,
    "frida": 10.0, "tamper": 8.0,
}

# Khối thuc thi hien dai da kiem chung (dang tin hon khi du doan)
MODERN_BLOCKS = ("SET_BOOL", "INIT", "HOOK_SCRIPT", "TRACE", "API_LOG",
                 "REMOTE_CONFIG")


def detect_protections(texts):
    """Quet nhanh dau hieu bao ve trong cache noi dung cây APK."""
    if not texts:
        return []
    hits = {name: {"loại": name, "tên": name, "lần": 0, "tệp": set()}
            for name, _ in PROTECTION_PATTERNS}
    for rel, text in texts.items():
        for name, keywords in PROTECTION_PATTERNS:
            for kw in keywords:
                if kw in text:
                    hits[name]["lần"] += 1
                    hits[name]["tệp"].add(rel)
    found = []
    for h in hits.values():
        if h["lần"]:
            h["tệp"] = sorted(h["tệp"])[:5]
            found.append(h)
    return sorted(found, key=lambda x: -x["lần"])


def detect_protections_fast(tree_root, cache=None):
    """Quet nhanh dau hieu bao ve bang rg (khong nap toan bo text vao RAM).

    `lần` la so tệp chua dau hieu — bang chung do duoc tu du lieu that.
    """
    from .advisor import ScanCache
    sc = cache if cache is not None else ScanCache(tree_root)
    keywords = [kw for _name, kws in PROTECTION_PATTERNS for kw in kws]
    sc.ensure(keywords)
    found = []
    for name, kws in PROTECTION_PATTERNS:
        files = set()
        for kw in kws:
            files |= sc.candidates(kw) or set()
        if files:
            found.append({"loại": name, "tên": name,
                          "lần": len(files), "tệp": sorted(files)[:5]})
    return sorted(found, key=lambda x: -x["lần"])


def _cap_priority(caps):
    if not caps:
        return 0.05
    return max(CAP_PRIORITY.get(c, 0.05) for c in caps)


def estimate_success(cov, caps, protections, modern_ratio=0.0):
    """Uoc luong ty le thanh cong (%) va giai thich cac yeu to anh huong."""
    matches = sum(d.get("khớp", 0) for d in cov.get("chi_tiết", []))
    quy_tac = max(1, cov.get("quy_tắc", 0))
    phan = 100.0 * (
        0.45 * cov.get("tỷ_lệ", 0.0)
        + 0.20 * min(1.0, matches / 25.0)
        + 0.15 * min(1.0, cov.get("quy_tắc_khớp", 0) / quy_tac)
        + 0.10 * _cap_priority(caps)
        + 0.10 * min(1.0, modern_ratio)
    )
    factors = [
        ("Bao phu quy tac khớp %.0f%%" % (cov.get("tỷ_lệ", 0.0) * 100),
         0.45 * cov.get("tỷ_lệ", 0.0) * 100),
        ("So lần khớp %d (toi da 25)" % matches,
         0.20 * min(1.0, matches / 25.0) * 100),
        ("Khối khớp %d/%d" % (cov.get("quy_tắc_khớp", 0), quy_tac),
         0.15 * min(1.0, cov.get("quy_tắc_khớp", 0) / quy_tac) * 100),
        ("Do uu tien nang luc %.2f" % _cap_priority(caps),
         0.10 * _cap_priority(caps) * 100),
    ]
    if modern_ratio:
        factors.append(("Ty le khối hien dai %.0f%%" % (modern_ratio * 100),
                        0.10 * modern_ratio * 100))
    penalties = []
    for p in protections:
        pen = PROTECTION_PENALTY.get(p["loại"], 10.0)
        penalties.append((p["loại"], pen))
        phan -= pen
    rate = max(0.0, min(100.0, phan))
    return {
        "tỷ_lệ": round(rate, 1),
        "yeu_to": [{"tên": n, "điểm": round(v, 1)} for n, v in factors],
        "phat": [{"loại": n, "điểm": round(v, 1)} for n, v in penalties],
    }


def _modern_ratio(patch):
    """Ty le khối thuc thi hien dai trong patch (0..1)."""
    if not getattr(patch, "sections", None):
        return 0.0
    types = [s.type for s in patch.sections if s.type]
    if not types:
        return 0.0
    return sum(1 for t in types if t in MODERN_BLOCKS) / float(len(types))


def _tooling_for(caps):
    """Gop cach lam + cong cu tu danh sach nang luc."""
    seen = []
    tools = []
    for c in caps:
        t = CAP_TOOLING.get(c)
        if not t or c in seen:
            continue
        seen.append(c)
        for tool in t["cong_cu"]:
            if tool not in tools:
                tools.append(tool)
    return {
        "cách": [CAP_TOOLING[c]["cach"] for c in seen],
        "công_cụ": tools,
        "xác_minh": [CAP_TOOLING[c]["xac_minh"] for c in seen],
    }


def _bypass_points(cov):
    """Liet ke điểm bypass cu the tu chi tiet coverage."""
    points = []
    for d in cov.get("chi_tiết", []):
        if not d.get("khớp"):
            continue
        points.append({
            "khối": d.get("khối"), "loại": d.get("loại"),
            "target": d.get("target"),
            "khớp": d.get("khớp"),
            "tệp_trúng": d.get("tệp_trúng", [])[:10],
            "biến_thể": d.get("biến_thể", [])[:3],
        })
    return points


def _suggestions(cov):
    """De xuat tang kha nang thanh cong dua tren du lieu quet."""
    sug = []
    for d in cov.get("chi_tiết", []):
        if d.get("biến_thể"):
            sug.append("Mo rong MATCH khối %s: %s"
                       % (d.get("khối"), d.get("biến_thể")[0]))
        if d.get("ngoai_target"):
            rel, n = d["ngoai_target"][0]
            sug.append("Chuoi khối %s con xuat hien ngoai target (%s, %d lần) — "
                       "can nhac bo sung class-link"
                       % (d.get("khối"), rel, n))
        if not d.get("khớp") and d.get("target"):
            sug.append("Khối %s truot target %s — cap nhat TARGET theo "
                       "class-link that cua APK" % (d.get("khối"),
                                                    d.get("target")))
    return sug[:6]


def build_bypass_report(tree, scored, combos, texts=None, limit=10,
                        protections=None):
    """Sinh bao cao bypass tu du lieu quet (scored patches + combos)."""
    if protections is None:
        protections = detect_protections(texts or {})
    items = []
    for x in scored[:limit]:
        cov = {
            "quy_tắc": x.get("rules", 0),
            "quy_tắc_khớp": x.get("rules_matched", 0),
            "tỷ_lệ": x.get("coverage", 0.0),
            "chi_tiết": x.get("chi_tiết", []),
        }
        rate = estimate_success(cov, x.get("capabilities", []),
                                protections, x.get("modern_ratio", 0.0))
        items.append({
            "patch": x["patch"],
            "điểm": x.get("score", 0.0),
            "tỷ_lệ_thành_công": rate["tỷ_lệ"],
            "phân_tích": rate,
            "năng_lực": x.get("capabilities", []),
            "điểm_bypass": _bypass_points(cov),
            "cách_công_cụ": _tooling_for(x.get("capabilities", [])),
            "đề_xuất": _suggestions(cov),
        })
    combo_items = []
    for c in combos[:limit]:
        a = next((i for i in items if i["patch"] == c["patches"][0]), None)
        b = next((i for i in items if i["patch"] == c["patches"][1]), None)
        if not a or not b:
            continue
        rate = round(min(100.0, (a["tỷ_lệ_thành_công"]
                                 + b["tỷ_lệ_thành_công"]) / 2.0
                         + min(len(c.get("support", [])), 6) * 0.8), 1)
        combo_items.append({
            "patches": c["patches"],
            "tỷ_lệ_thành_công": rate,
            "năng_lực": c.get("capabilities", []),
            "bo_tro": c.get("support", []),
        })
    best = items[0] if items else None
    best_combo = combo_items[0] if combo_items else None
    plan = _deploy_plan(best, best_combo, protections)
    return {
        "tree": tree,
        "protections": protections,
        "top_patches": items,
        "top_combos": combo_items,
        "plan": plan,
    }


def _deploy_plan(best, best_combo, protections):
    """De xuat phuong an trien khai theo buoc + cach tang kha nang thanh cong."""
    if not best:
        return None
    patches = [best["patch"]]
    label = best["patch"]
    if best_combo and best_combo["patches"][0] == best["patch"]:
        patches = list(best_combo["patches"])
        label = " + ".join(patches)
    steps = [
        "Chuan bi cây APK (apk-prepare) hoac dung cây da giai ma.",
        "Ap patch: python3 patchx apply %s <cây-apk>" % " ".join(patches),
        "Chuan hoa resource chua `$`: python3 patchx_toolkit.py apk-fix-res",
        "Build: apktool b <cây> -o out.apk --aapt <aapt2-that>",
        "Zipalign + ky: zipalign -f 4 && apksigner sign",
        "Cai APK, xac minh dong bang logcat/Frida theo mức xac_minh.",
    ]
    risks = []
    for p in protections:
        risks.append("APK co dau hieu %s (%d lần) — tru ~%.0f%% điểm du doan; "
                     "uu tien patch integrity/token xu ly lop nay."
                     % (p["loại"], p["lần"],
                        PROTECTION_PENALTY.get(p["loại"], 10.0)))
    return {
        "phương_án": label,
        "tỷ_lệ_dự_đoán": best["tỷ_lệ_thành_công"],
        "steps": steps,
        "rủi_ro": risks[:4],
        "tăng_khả_năng": best.get("đề_xuất", []),
    }


def render_markdown(report):
    """Dung bao cao Markdown tu dict bao cao."""
    lines = ["# Bao cao quet chi tiet — phuong an bypass", "",
             "- Cay APK: `%s`" % report["tree"], ""]
    if report["protections"]:
        lines += ["## Lop bao ve phat hien", "",
                  "| Loai | So lần | Tep vi du |",
                  "|------|-------:|-----------|"]
        for p in report["protections"]:
            files = ", ".join("`%s`" % f for f in p["tệp"])
            lines.append("| %s | %d | %s |" % (p["loại"], p["lần"], files))
        lines.append("")
    lines += ["## Patch don — điểm bypass, cong cu, ty le thanh cong", "",
              "| Hang | Patch | Diem | Thanh cong | Khop | Nang luc |",
              "|------|-------|-----:|-----------:|-----:|----------|"]
    for i, it in enumerate(report["top_patches"], 1):
        lines.append("| %d | %s | %.3f | %.0f%% | %d | %s |" % (
            i, it["patch"], it["điểm"], it["tỷ_lệ_thành_công"],
            sum(p["khớp"] for p in it["điểm_bypass"]),
            ", ".join(sorted(it.get("năng_lực", [])))))
    for it in report["top_patches"]:
        lines += ["", "### %s — du doan %.0f%%" % (it["patch"],
                                                   it["tỷ_lệ_thành_công"])]
        if it["cách_công_cụ"]["cách"]:
            lines.append("")
            for c in it["cách_công_cụ"]["cách"]:
                lines.append("- Cach: %s" % c)
            lines.append("- Cong cu: %s"
                         % ", ".join("`%s`" % t
                                     for t in it["cách_công_cụ"]["công_cụ"]))
        if it["điểm_bypass"]:
            lines += ["", "Diem bypass cu the:"]
            for p in it["điểm_bypass"][:8]:
                files = ", ".join("`%s`" % f for f in p["tệp_trúng"][:4])
                lines.append("- Khối %s (%s) target `%s`: %d khớp — %s"
                             % (p["khối"], p["loại"], p["target"],
                                p["khớp"], files))
        if it["đề_xuất"]:
            lines += ["", "De xuat tang kha nang thanh cong:"]
            for s in it["đề_xuất"]:
                lines.append("- %s" % s)
    if report["top_combos"]:
        lines += ["", "## Combo bo tro", "",
                  "| Patch 1 | Patch 2 | Thanh cong | Bo tro |",
                  "|---------|---------|-----------:|--------|"]
        for c in report["top_combos"]:
            lines.append("| %s | %s | %.0f%% | %s |" % (
                c["patches"][0], c["patches"][1], c["tỷ_lệ_thành_công"],
                ", ".join("%s→%s" % s for s in c["bo_tro"][:3])))
    if report["plan"]:
        pl = report["plan"]
        lines += ["", "## Phương án triển khai đề xuất", "",
                  "- Phương án: %s" % pl["phương_án"],
                  "- Tỷ lệ thành công dự đoán: %.0f%%" % pl["tỷ_lệ_dự_đoán"],
                  ""]
        for i, s in enumerate(pl["steps"], 1):
            lines.append("%d. %s" % (i, s))
        if pl["rủi_ro"]:
            lines += ["", "Rủi ro:"]
            for r in pl["rủi_ro"]:
                lines.append("- %s" % r)
        if pl["tăng_khả_năng"]:
            lines += ["", "Đề xuất nâng tỷ lệ:"]
            for s in pl["tăng_khả_năng"]:
                lines.append("- %s" % s)
    return "\n".join(lines)
