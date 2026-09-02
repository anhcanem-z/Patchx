# -*- coding: utf-8 -*-
"""pairip-bypass — vô hiệu hóa PairIP (license check) trên cây APK đã giải mã.

PairIP (com.pairip.*) là lớp bảo vệ license chèn vào app; bản thường không có
lib native riêng (libpairipcore.so). Entry point thật:

- com.pairip.application.Application.attachBaseContext
  -> LicenseClient.checkLicense (chạy ngay khi app khởi động)
- LicenseContentProvider.onCreate -> LicenseClient.checkLicense
- LicenseActivity (màn hình chặn PAYWALL / ERROR_DIALOG, tự thoát app)
- LicenseClient.checkLicense / stopTrial / handleTrialEnd / initializeLicenseCheck
  (luồng kiểm tra + hết trial 3 phút -> paywall)

Bypass: bỏ gọi checkLicense ở 2 entry point + vô hiệu hóa 4 method trong
LicenseClient (nop, return-void) + LicenseActivity.onStart tự finish ngay.

Luồng: detect -> plan (JSON+MD) -> [--apply] backup + patch (idempotent).
Chạy:  patchx pairip-bypass CÂY [--apply]
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = "patchx.pairip-bypass/v1"

# Các thư mục smali có thể chứa com/pairip (dex 1..N)
SMALI_DIRS = ("smali", "smali_classes2", "smali_classes3", "smali_classes4")

MANIFEST_MARKERS = (
    "com.pairip.application.Application",
    "com.pairip.licensecheck.LicenseActivity",
    "com.pairip.licensecheck.LicenseContentProvider",
    "com.android.vending.CHECK_LICENSE",
)

# (đường dẫn tương đối trong thư mục smali, method, hành động)
PATCH_SPECS = (
    ("com/pairip/application/Application.smali", "attachBaseContext", "remove_call"),
    ("com/pairip/licensecheck/LicenseContentProvider.smali", "onCreate", "remove_call"),
    ("com/pairip/licensecheck/LicenseClient.smali", "checkLicense", "nop"),
    ("com/pairip/licensecheck/LicenseClient.smali", "stopTrial", "nop"),
    ("com/pairip/licensecheck/LicenseClient.smali", "handleTrialEnd", "nop"),
    ("com/pairip/licensecheck/LicenseClient.smali", "initializeLicenseCheck", "nop"),
    ("com/pairip/licensecheck/LicenseActivity.smali", "onStart", "finish"),
)

_NOP_BODY_RE = re.compile(r"^\s*\.locals\s+\d+\s+return-void\s*$", re.DOTALL)
_CHECK_CALL_RE = re.compile(
    r"\n?[ \t]*invoke-static \{[^}]*\}, "
    r"Lcom/pairip/licensecheck/LicenseClient;->checkLicense\(Landroid/content/Context;\)V\n")
_PROVIDER_BLOCK_RE = re.compile(
    r"[ \t]*invoke-virtual \{p0\}, "
    r"Lcom/pairip/licensecheck/LicenseContentProvider;->getContext\(\)"
    r"Landroid/content/Context;\n\n"
    r"[ \t]*move-result-object v0\n\n"
    r"[ \t]*invoke-static \{v0\}, "
    r"Lcom/pairip/licensecheck/LicenseClient;->checkLicense\(Landroid/content/Context;\)V\n")


def _find_smali_file(tree_path: Path, rel: str) -> Optional[Path]:
    """Tìm file smali tương đối trong các thư mục smali* của cây."""
    for d in SMALI_DIRS:
        p = tree_path / d / rel
        if p.is_file():
            return p
    return None


def detect_pairip(tree) -> dict[str, Any]:
    """Phát hiện PairIP trên cây APK (chỉ đọc)."""
    tree_path = Path(tree).expanduser().resolve()
    found_files: dict[str, Optional[str]] = {}
    for rel, _m, _a in PATCH_SPECS:
        fp = _find_smali_file(tree_path, rel)
        found_files[rel] = str(fp) if fp else None

    manifest_path = tree_path / "AndroidManifest.xml"
    manifest_hits: list[str] = []
    if manifest_path.is_file():
        try:
            text = manifest_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        manifest_hits = [m for m in MANIFEST_MARKERS if m in text]

    native_libs: list[str] = []
    for lib_dir in (tree_path / "lib", tree_path / "assets"):
        if lib_dir.is_dir():
            native_libs += sorted(str(p) for p in lib_dir.rglob("libpairip*"))

    license_client = found_files.get(
        "com/pairip/licensecheck/LicenseClient.smali")
    found = bool(license_client) or bool(manifest_hits)
    return {
        "found": found,
        "root": str(tree_path),
        "license_client": license_client,
        "license_activity": found_files.get(
            "com/pairip/licensecheck/LicenseActivity.smali"),
        "application": found_files.get(
            "com/pairip/application/Application.smali"),
        "provider": found_files.get(
            "com/pairip/licensecheck/LicenseContentProvider.smali"),
        "manifest_hits": manifest_hits,
        "native_libs": native_libs,
        "smali_files": found_files,
    }


def _method_body(content: str, name: str) -> Optional[str]:
    pattern = re.compile(
        r"(\.method[^\n]*?\b%s\([^\n]*\n)(.*?)(\.end\s+method)" % re.escape(name),
        re.DOTALL)
    hit = pattern.search(content)
    return hit.group(2) if hit else None


def _is_nop_body(body: Optional[str]) -> bool:
    return bool(body) and bool(_NOP_BODY_RE.match(body))


def _is_already(rel: str, name: str, content: str, action: str) -> bool:
    """Kiểm tra mục tiêu đã được vá trước đó (idempotent)."""
    if action == "remove_call":
        return not _CHECK_CALL_RE.search(content)
    if action == "nop":
        return _is_nop_body(_method_body(content, name))
    if action == "finish":
        body = _method_body(content, name)
        return bool(body) and "->finish()V" in body
    return False


def _patch_remove_call(content: str) -> tuple[str, bool]:
    """Bỏ lệnh invoke checkLicense (Application / LicenseContentProvider)."""
    new_content, count = _PROVIDER_BLOCK_RE.subn("", content)
    if count:
        return new_content, True
    new_content, count = _CHECK_CALL_RE.subn("", content)
    if count:
        return new_content, True
    return content, False


def _patch_nop(content: str, name: str) -> tuple[str, bool]:
    """Thay toàn bộ thân method (void) bằng return-void."""
    new_body = "    .locals 0\n\n    return-void\n"

    def replace_body(match: re.Match) -> str:
        return match.group(1) + new_body + match.group(3)

    new_content, count = re.compile(
        r"(\.method[^\n]*?\b%s\([^\n]*\n)(.*?)(\.end\s+method)" % re.escape(name),
        re.DOTALL).subn(replace_body, content)
    return (new_content, count > 0)


def _patch_finish(content: str) -> tuple[str, bool]:
    """LicenseActivity.onStart: chỉ giữ invoke-super + finish."""
    new_method = (
        ".method public onStart()V\n"
        "    .locals 1\n\n"
        "    invoke-super {p0}, Landroid/app/Activity;->onStart()V\n\n"
        "    invoke-virtual {p0}, "
        "Lcom/pairip/licensecheck/LicenseActivity;->finish()V\n\n"
        "    return-void\n"
        ".end method\n")
    pattern = re.compile(
        r"\.method[^\n]*?\bonStart\([^\n]*\n.*?\.end\s+method\n", re.DOTALL)
    new_content, count = pattern.subn(new_method, content, count=1)
    return (new_content, count > 0)


def build_pairip_plan(tree) -> dict[str, Any]:
    """Lập kế hoạch bypass PairIP (chỉ đọc, không ghi smali)."""
    det = detect_pairip(tree)
    patches: list[dict[str, Any]] = []
    for rel, name, action in PATCH_SPECS:
        fp = det["smali_files"].get(rel)
        if not fp:
            patches.append({
                "file": rel, "method": name, "action": action,
                "status": "not_found",
            })
            continue
        content = Path(fp).read_text(encoding="utf-8", errors="ignore")
        if _is_already(rel, name, content, action):
            patches.append({
                "file": rel, "method": name, "action": action,
                "status": "already_patched",
            })
            continue
        body_ok = bool(_method_body(content, name))
        patches.append({
            "file": rel, "method": name, "action": action,
            "status": "patchable" if body_ok else "method_missing",
        })
    stats = {
        "total": len(patches),
        "patchable": sum(1 for p in patches if p["status"] == "patchable"),
        "already_patched": sum(1 for p in patches
                               if p["status"] == "already_patched"),
        "not_found": sum(1 for p in patches if p["status"] == "not_found"),
        "method_missing": sum(1 for p in patches
                              if p["status"] == "method_missing"),
    }
    return {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tree": str(Path(tree).expanduser().resolve()),
        "detected": det,
        "patches": patches,
        "stats": stats,
    }


def _backup_files(tree_path: Path, sources: list[str],
                  backup_dir: Path) -> list[str]:
    """Backup từng file smali trước khi ghi (giữ cấu trúc tương đối)."""
    created = []
    for src in sources:
        src_path = Path(src)
        try:
            rel = src_path.relative_to(tree_path)
        except ValueError:
            rel = Path(src_path.name)
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst)
        created.append(str(dst))
    return created


def render_pairip_markdown(report: dict[str, Any]) -> str:
    """Báo cáo Markdown (tiếng Việt, có dấu)."""
    det = report["detected"]
    lines = [
        "# Bypass PairIP — báo cáo", "",
        "- Cây APK: `%s`" % report["tree"],
        "- Thời điểm: %s" % report["generated"],
        "- Phát hiện PairIP: %s" % ("có" if det["found"] else "KHÔNG"),
        "- Application (entry): %s" % ("có" if det["application"] else "không"),
        "- LicenseContentProvider: %s" % ("có" if det["provider"] else "không"),
        "- LicenseClient: %s" % ("có" if det["license_client"] else "không"),
        "- LicenseActivity: %s" % ("có" if det["license_activity"] else "không"),
        "- Manifest (khớp): %s" % (", ".join(det["manifest_hits"]) or "—"),
        "- Lib native pairip: %s" % (", ".join(det["native_libs"]) or "không có"),
        "",
    ]
    if det["found"]:
        stats = report["plan"]["stats"]
        lines += [
            "## Kế hoạch", "",
            "| Tệp | Method | Hành động | Trạng thái |",
            "|---|---|---|---|",
        ]
        for p in report["plan"]["patches"]:
            lines.append("| `%s` | %s | %s | %s |" % (
                p["file"], p["method"], p["action"], p["status"]))
        lines.append("")
        lines.append("Tổng: %d | Cần vá: %d | Đã vá sẵn: %d | "
                     "Thiếu file: %d | Thiếu method: %d" % (
                         stats["total"], stats["patchable"],
                         stats["already_patched"], stats["not_found"],
                         stats["method_missing"]))
        lines.append("")
    patched = report.get("patched")
    if patched:
        lines += [
            "## Kết quả áp patch", "",
            "- Thành công: %d | Lỗi: %d | Đã vá sẵn: %d" % (
                patched["success"], patched["failed"],
                patched.get("already", 0)),
            "- Backup: `%s`" % patched.get("backup_dir", "—"),
            "",
        ]
        if patched.get("details"):
            lines += ["| Tệp | Trạng thái |", "|---|---|"]
            for d in patched["details"]:
                lines.append("| `%s` | %s |" % (d["file"], d["status"]))
            lines.append("")
    return "\n".join(lines)


def apply_pairip_bypass(tree, out_dir, apply: bool = False,
                        backup: bool = True,
                        dry_run: bool = False) -> dict[str, Any]:
    """Chạy pairip-bypass: lập kế hoạch; --apply ghi smali sau khi backup."""
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    plan = build_pairip_plan(tree)
    tree_path = Path(plan["tree"])
    report = {
        "schema": SCHEMA,
        "generated": plan["generated"],
        "tree": plan["tree"],
        "detected": plan["detected"],
        "plan": plan,
        "dry_run": bool(dry_run),
    }
    (out_path / "pairip_bypass_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_path / "pairip_bypass_plan.md").write_text(
        render_pairip_markdown(report) + "\n", encoding="utf-8")

    patched = None
    if apply and not dry_run:
        targets = [p for p in plan["patches"]
                   if p["status"] == "patchable"]
        if targets:
            sources = []
            seen = set()
            for p in targets:
                fp = plan["detected"]["smali_files"].get(p["file"])
                if fp and fp not in seen:
                    seen.add(fp)
                    sources.append(fp)
            backup_dir = None
            backup_files: list[str] = []
            if backup:
                backup_dir = out_path / "backup"
                backup_files = _backup_files(tree_path, sources, backup_dir)
            details = []
            success = failed = 0
            for p in targets:
                fp = plan["detected"]["smali_files"].get(p["file"])
                if not fp:
                    failed += 1
                    details.append({"file": p["file"], "status": "failed"})
                    continue
                content = Path(fp).read_text(encoding="utf-8",
                                             errors="ignore")
                if p["action"] == "remove_call":
                    new_content, ok = _patch_remove_call(content)
                elif p["action"] == "nop":
                    new_content, ok = _patch_nop(content, p["method"])
                elif p["action"] == "finish":
                    new_content, ok = _patch_finish(content)
                else:
                    new_content, ok = content, False
                if ok:
                    Path(fp).write_text(new_content, encoding="utf-8")
                    success += 1
                    details.append({"file": p["file"],
                                    "status": "patched",
                                    "method": p["method"],
                                    "action": p["action"]})
                else:
                    failed += 1
                    details.append({"file": p["file"],
                                    "status": "failed",
                                    "method": p["method"]})
            patched = {
                "success": success,
                "failed": failed,
                "already": plan["stats"]["already_patched"],
                "details": details,
                "backup_dir": str(backup_dir) if backup_dir else None,
                "backup_files": backup_files,
            }
        else:
            patched = {
                "success": 0,
                "failed": 0,
                "already": plan["stats"]["already_patched"],
                "details": [],
                "backup_dir": None,
                "backup_files": [],
            }
        report["patched"] = patched

    (out_path / "pairip_bypass_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = render_pairip_markdown(report)
    (out_path / "pairip_bypass_report.md").write_text(
        md + "\n", encoding="utf-8")
    return report
