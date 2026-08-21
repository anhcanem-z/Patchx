# -*- coding: utf-8 -*-
"""P15 — Failure Intelligence: DB lỗi + sinh regression test.

Moi lỗi co ERROR_ID, STAGE, pattern (regex khớp thong bao), nguyen nhan,
cach xu ly va test hoi quy. `classify_failure` gan ERROR_ID cho lỗi moi;
`gen_regression_test` sinh test tu dong tu mot entry.
"""

import json
import os
import re
import time

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "failure_db.json")

DEFAULT_FAILURES = [
    {
        "error_id": "F-BUILD-001",
        "stage": "BUILD",
        "pattern": r"Syntax error: \"\(\" unexpected",
        "cause": ("Wrapper aapt2 cua Termux bi lỗi shell (tệp tam aapt2_*.tmp "
                  "khong chay duoc)."),
        "fix": ("Dung aapt2 that: apktool b CAY -o OUT.apk "
                "--aapt /data/data/com.termux/files/usr/bin/aapt2"),
        "regression": "test_golden_rebuild",
    },
    {
        "error_id": "F-BUILD-002",
        "stage": "BUILD",
        "pattern": r"has invalid entry name",
        "cause": "Ten resource chua ky tu '$' lam aapt2 bao entry name lỗi.",
        "fix": ("Chay apk-fix-res de chuan hoa tên resource, roi cap nhat "
                "tham chieu public.xml/drawable."),
        "regression": "test_resource_fix_sach_tham_chieu",
    },
    {
        "error_id": "F-BUILD-003",
        "stage": "SIGN",
        "pattern": r"e_type",
        "cause": "Zipalign bao lỗi e_type (ELF 32/64 bit khong khớp).",
        "fix": "Bo qua zipalign (fallback) hoac dung zipalign dung kien truc; "
               "apksigner verify v1/v2/v3 van đạt.",
        "regression": "test_package_gioi_han_3_ban",
    },
    {
        "error_id": "F-DEX-001",
        "stage": "PREFLIGHT",
        "pattern": r"method refs.*vuot|DEX.*(BLOCK|overflow)|65536",
        "cause": "Cay APK vuot gioi han 64K method refs cua mot dex.",
        "fix": "Khong apply; giam refs (xoa code/khối REMOVE_FILES) hoac "
               "chia multi-dex trước khi patch.",
        "regression": "test_dex_budget",
    },
    {
        "error_id": "F-DEX-002",
        "stage": "BUILD",
        "pattern": (r"Unsigned short value out of range|"
                    r"Invalid or truncated dex file|"
                    r"Failed to open dex file|"
                    r"class has already been interned"),
        "cause": ("Apktool/smali de lai classes*.dex do dang khi build fail "
                  "hoac bi retry dung cache cu: header DEX zero/thieu; "
                  "thuong gap khi method_ids da cham 64K roi patch them "
                  "method ref."),
        "fix": ("Xoa tree/build trước moi lần build/retry (da co trong "
                "_build_apktool); neu van bao Unsigned short out of range "
                "thi tach bot smali sang smali_classesN de moi dex duoi 64K, "
                "roi apk-fix-res + build lai."),
        "regression": "test_failure_dex_cache_p15",
    },
    {
        "error_id": "F-PATCH-001",
        "stage": "APPLY",
        "pattern": r"lỗi nen|Bad CRC|Corrupt|ZipFile|invalid entry",
        "cause": "Zip patch nguon hong (entry nen lỗi) — vi du "
                 "SignatureHack_arm64.zip entry libfrida-gadget.so.",
        "fix": "Thay ban lầnh tu Modder Hub; quet dupes theo hash; sao luu "
               "ban hong trước khi thay.",
        "regression": "test_corrupt_zip",
    },
    {
        "error_id": "F-RUNTIME-001",
        "stage": "RUNTIME_M2",
        "pattern": r"FATAL EXCEPTION|ANR in",
        "cause": "App crash/ANR khi chay (runtime M2 that bai).",
        "fix": "Doc crash_lines/anr_lines trong runtime_report.json, sua "
               "patch gay lỗi, build lai va verify lai.",
        "regression": "test_runtime_status_p13",
    },
    {
        "error_id": "F-ENV-001",
        "stage": "ENV",
        "pattern": r"Address already in use|Errno 98",
        "cause": "Cong server webui da co tien trinh khac chiem giu.",
        "fix": "Tat server cu (pkill -f webui/server.py) hoac doi --port.",
        "regression": "test_report_dashboard",
    },
    {
        "error_id": "F-SCAN-001",
        "stage": "SCAN",
        "pattern": r"MemoryError|RecursionError|Killed",
        "cause": "APK cây lon (hang tram MB) lam regex toan cây ton bo nho.",
        "fix": "Dung fast scanner (rg/hash/index + cache theo hash APK), "
               "roadmap thay vi quet toan cây, gioi han mau.",
        "regression": "test_bench_scan",
    },
    {
        "error_id": "F-SEM-001",
        "stage": "PLAN",
        "pattern": r"AMBIGUOUS_TARGET",
        "cause": ("Semantic-plan V2 co nhieu ung vien đạt chinh sach; chon "
                  "ung vien dung dau se la duong tinh gia tiem an."),
        "fix": ("Khong tu chon: siet selector.all/near_entry, tang min_score "
                "hoac trinh nguoi dung chon dung mot ung vien."),
        "regression": "test_semantic_evidence_v2",
    },
    {
        "error_id": "F-SEM-002",
        "stage": "PLAN",
        "pattern": r"INSUFFICIENT_EVIDENCE",
        "cause": ("Thieu app-model/V2 hoac thieu du lieu can thiet de danh "
                  "gia selector cua semantic-plan V2."),
        "fix": ("Sinh model V2 bang `patchx model CAY --v2` trước, roi chay "
                "lai `patchx semantic-plan CAY PLAN`."),
        "regression": "test_semantic_evidence_v2",
    },
    {
        "error_id": "F-SEM-003",
        "stage": "PREFLIGHT",
        "pattern": r"cây APK da thay doi",
        "cause": ("Draft V2 khoa hash cây APK, nhung cây da bi sua sau khi "
                  "compile plan — evidence khong con dung."),
        "fix": ("Khong ap draft: chay lai semantic-plan + plan-compile tren "
                "cây hien tai de khoa evidence moi."),
        "regression": "test_semantic_evidence_v2",
    },
    {
        "error_id": "F-SEM-004",
        "stage": "PLAN",
        "pattern": r"NO_CONFIDENT_TARGET",
        "cause": ("Khong co ung vien đạt min_score: selector qua chat hoac "
                  "ma dich da doi cau truc/ngu nghia."),
        "fix": ("Noi selector co kiem soat hoac dung version-map/knowledge V2 "
                "de tim ung vien tuong dong roi danh gia lai."),
        "regression": "test_semantic_evidence_v2",
    },
]


def _ensure_db_path(db_path):
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    return os.path.abspath(db_path)


def load_db(db_path=None):
    """Doc DB — hop nhat entry mac dinh + entry tuy chinh (neu co)."""
    path = _ensure_db_path(db_path)
    entries = list(DEFAULT_FAILURES)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                extra = json.load(fh)
            if isinstance(extra, list):
                entries.extend(extra)
        except (OSError, ValueError):
            pass
    return entries


def save_db(entries, db_path=None):
    path = _ensure_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
    return path


def add_failure(entry, db_path=None):
    """Them entry — ERROR_ID phai duy nhat; tra entry da them."""
    eid = str(entry.get("error_id", "")).strip()
    if not eid:
        raise ValueError("error_id khong duoc de trong")
    if not entry.get("pattern"):
        raise ValueError("pattern khong duoc de trong")
    entries = load_db(db_path)
    if any(e.get("error_id") == eid for e in entries):
        raise ValueError("error_id da ton tai: %s" % eid)
    for key in ("stage", "cause", "fix", "regression"):
        entry.setdefault(key, "")
    entries.append(entry)
    path = save_db(entries, db_path)
    return entry, path


def classify_failure(message, stage=None, db_path=None):
    """Tim entry khớp thong bao — tra entry dau tien (hoac None)."""
    if not message:
        return None
    for e in load_db(db_path):
        if stage and e.get("stage") != stage:
            continue
        try:
            if re.search(e["pattern"], message, re.I):
                return e
        except re.error:
            continue
    return None


def render_report(db_path=None):
    entries = load_db(db_path)
    lines = ["# Failure Intelligence (P15)", "",
             "| ERROR_ID | Stage | Pattern | Nguyên nhân | Xu ly | Regression |",
             "|----------|-------|---------|-------------|-------|------------|"]
    for e in entries:
        lines.append("| %s | %s | `%s` | %s | %s | %s |"
                     % (e.get("error_id"), e.get("stage"), e.get("pattern"),
                        e.get("cause"), e.get("fix"),
                        e.get("regression")))
    lines.append("")
    lines.append("Tổng: %d lỗi trong DB." % len(entries))
    return "\n".join(lines)


def gen_regression_test(entry, test_name=None):
    """Sinh ma test Python tu entry — tra chuoi nguon test."""
    eid = entry.get("error_id", "F-XXX")
    stage = entry.get("stage", "")
    pattern = entry["pattern"]
    test_name = test_name or ("test_failure_" + re.sub(r"[^A-Za-z0-9]", "_",
                                                       eid).lower())
    return (
        f"def {test_name}():\n"
        f"    \"\"\"P15 — Regression cho {eid} (stage {stage}).\"\"\"\n"
        f"    from patchx_core.failure_db import classify_failure\n"
        f"    hit = classify_failure({pattern!r}, stage={stage!r})\n"
        f"    check(\"P15: {eid} phan loại dung\",\n"
        f"          hit is not None and hit[\"error_id\"] == {eid!r},\n"
        f"          str(hit.get(\"error_id\") if hit else None))\n"
    )
