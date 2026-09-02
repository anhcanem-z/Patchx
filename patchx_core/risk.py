# -*- coding: utf-8 -*-
"""T5 — co rui ro chuoi cung ung: phat hien hanh vi nguy hiem trong patch
(gui du lieu ra ngoai, tat bao mat he thong) → canh bao trong bao cao.

Luu y: chi la phat hien tinh theo quy tac — khong phan quyet phap ly.
"""

import re


RISK_RULES = [
    ("gửi-dữ-liệu",
     "URL http/https trong noi dung patch — co the gui du lieu ra ngoai",
     re.compile(r"https?://", re.I)),
    ("gửi-dữ-liệu",
     "goi HttpURLConnection / Socket / OkHttp / Retrofit trong smali",
     re.compile(r"(HttpURLConnection|Ljava/net/Socket|okhttp|Retrofit)",
                re.I)),
    ("tắt-bảo-mật",
     "vo hieu hoa kiem tra (sigcheck/verify) hoac bat debuggable/cleartext",
     re.compile(r"(sigcheck|verify\s*\(|allowBackup=\"true\"|"
                r"usesCleartextTraffic=\"true\"|debuggable=\"true\")", re.I)),
    ("quyền-hệ-thống",
     "cap quyen he thong (pm grant / setComponentEnabledSetting)",
     re.compile(r"(pm grant|setComponentEnabledSetting|grantUriPermission)",
                re.I)),
    ("thu-thập",
     "doc du lieu nhay cam (IMEI / device id / tai khoan / oauth)",
     re.compile(r"(getDeviceId|IMEI|getSubscriberId|getAccounts|oauth)", re.I)),
    ("mạng-ngầm",
     "REMOTE_CONFIG / CONFIG_URL — tai cau hinh tu xa",
     re.compile(r"CONFIG_URL|REMOTE_CONFIG")),
]


def _section_text(sec):
    keys = ("MATCH", "REPLACE", "ASSIGN", "GOTO", "CODE", "VALUE", "SOURCE",
            "SCRIPT", "TARGET", "METHOD", "CONFIG_URL")
    parts = []
    for k in keys:
        v = sec.get(k)
        if v:
            parts.append(str(v))
    return "\n".join(parts)


def risk_findings(patch):
    """Quet patch — tra list dict {mức, loại, nội_dung, khối}."""
    out = []
    for sec in patch.sections:
        text = _section_text(sec)
        for loai, desc, rx in RISK_RULES:
            if rx.search(text):
                out.append({"mức": "rui-ro", "loại": loai,
                            "nội_dung": desc, "khối": sec.order})
    # Gop trung (nhieu khối cung quy tac → 1 canh bao)
    seen = set()
    uniq = []
    for f in out:
        key = f["loại"]
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq
