# -*- coding: utf-8 -*-
"""Tiếp nhận artifact Android hiện đại theo chế độ chỉ đọc.

Module này không giải mã toàn bộ APK và không sửa APK. Mục tiêu là tạo một
evidence report trước khi bất kỳ pipeline patch/build nào chạy:

* nhận diện APK/APKS/XAPK/AAB;
* kiểm kê DEX, ABI/native lib, manifest, split và chữ ký;
* lấy metadata Android từ aapt2/apksigner nếu có;
* ghi tool capabilities để phát hiện môi trường Termux thiếu công cụ.

Toàn bộ phần đọc archive sử dụng thư viện chuẩn, chỉ liệt kê ZipInfo; không
giải nén payload ứng dụng vào workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA = "patchx.intake/v1"
CAPABILITY_SCHEMA = "patchx.tool-capabilities/v1"
SUPPORTED_EXTENSIONS = {
    ".apk": "apk",
    ".apks": "apks",
    ".xapk": "xapk",
    ".aab": "aab",
}
MAX_TOOL_OUTPUT = 4096
MAX_NESTED_APK_ROWS = 128
_DEX_RE = re.compile(r"(?:^|/)classes(?:\d+)?\.dex$", re.I)
_CERT_RE = re.compile(r"certificate SHA-256 digest:\s*([0-9A-Fa-f:]+)", re.I)
_SCHEME_RE = re.compile(r"Verified using (v[1-4]) scheme[^:]*:\s*(true|false)", re.I)
_PACKAGE_RE = re.compile(
    r"^package:\s+name='([^']+)'(?:\s+versionCode='([^']*)')?(?:\s+versionName='([^']*)')?",
    re.M,
)
_SDK_RE = re.compile(r"^(targetSdkVersion|sdkVersion):'([^']+)'", re.M)
_PERMISSION_RE = re.compile(r"^uses-permission(?:-[^:]+)?:\s+name='([^']+)'", re.M)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:MAX_TOOL_OUTPUT]
    return ""


def _run_command(argv: Sequence[str], timeout: int = 15) -> Dict[str, Any]:
    """Chạy một probe read-only nhỏ và giữ output có giới hạn."""
    try:
        proc = subprocess.run(
            list(argv), text=True, capture_output=True, timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"returncode": None, "stdout": "", "stderr": "không tìm thấy"}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "quá thời gian"}
    except OSError as exc:
        return {"returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:MAX_TOOL_OUTPUT],
        "stderr": (proc.stderr or "")[:MAX_TOOL_OUTPUT],
    }


def _probe_tool(name: str, commands: Iterable[Sequence[str]]) -> Dict[str, Any]:
    command_rows = [list(c) for c in commands]
    binary = command_rows[0][0]
    executable = shutil.which(binary)
    row: Dict[str, Any] = {
        "name": name,
        "available": bool(executable),
        "path": executable,
        "version": None,
        "command": command_rows[0],
    }
    if not executable:
        row["detail"] = "không tìm thấy trong PATH"
        return row

    last: Dict[str, Any] = {}
    for command in command_rows:
        result = _run_command(command)
        last = result
        merged = (result.get("stdout", "") + "\n" + result.get("stderr", "")).strip()
        if result.get("returncode") == 0 and merged:
            row["command"] = list(command)
            row["version"] = _first_line(merged) or "không báo version"
            row["returncode"] = result.get("returncode")
            return row
    merged = (last.get("stdout", "") + "\n" + last.get("stderr", "")).strip()
    row["returncode"] = last.get("returncode")
    row["version"] = _first_line(merged) or "có binary nhưng không trả version"
    if last.get("stderr"):
        row["detail"] = _first_line(last["stderr"])
    return row


def collect_tool_capabilities() -> Dict[str, Any]:
    """Kiểm kê phiên bản công cụ mà không cài hoặc thay đổi môi trường."""
    probes: List[Tuple[str, List[List[str]]]] = [
        ("python3", [[sys.executable, "--version"]]),
        ("java", [["java", "-version"]]),
        ("apktool", [["apktool", "--version"], ["apktool", "version"]]),
        ("aapt2", [["aapt2", "version"]]),
        ("apksigner", [["apksigner", "--version"], ["apksigner", "version"]]),
        ("zipalign", [["zipalign", "--version"]]),
        ("adb", [["adb", "version"]]),
        ("jadx", [["jadx", "--version"]]),
        ("bundletool", [["bundletool", "version"]]),
        ("frida", [["frida", "--version"]]),
    ]
    tools = [_probe_tool(name, commands) for name, commands in probes]
    available = [row["name"] for row in tools if row["available"]]
    missing = [row["name"] for row in tools if not row["available"]]
    return {
        "schema": CAPABILITY_SCHEMA,
        "generated": _now(),
        "platform": sys.platform,
        "tools": tools,
        "summary": {
            "total": len(tools),
            "available": len(available),
            "missing": missing,
        },
    }


def _artifact_kind(path: str) -> str:
    return SUPPORTED_EXTENSIONS.get(os.path.splitext(path)[1].lower(), "unknown")


def _zip_rows(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    return [row for row in zf.infolist() if not row.is_dir()]


def _library_abis(names: Iterable[str]) -> Tuple[List[str], int]:
    abis = set()
    total = 0
    for name in names:
        parts = name.split("/")
        try:
            pos = parts.index("lib")
        except ValueError:
            continue
        if pos + 2 < len(parts) and parts[-1].endswith(".so"):
            abis.add(parts[pos + 1])
            total += 1
    return sorted(abis), total


def _split_role(name: str) -> str:
    lower = os.path.basename(name).lower()
    if lower in {"base.apk", "base-master.apk"} or lower.startswith("base-"):
        return "base"
    if "config." in lower or "split_config" in lower:
        return "config"
    if "feature" in lower or "split_" in lower:
        return "feature"
    return "unknown"


def _aapt_badging(apk_path: str) -> Dict[str, Any]:
    """Lấy metadata APK qua aapt2 nếu có; thất bại chỉ là evidence thiếu."""
    result: Dict[str, Any] = {
        "attempted": False,
        "available": bool(shutil.which("aapt2")),
        "package": None,
        "version_code": None,
        "version_name": None,
        "min_sdk": None,
        "target_sdk": None,
        "permissions": [],
        "detail": None,
    }
    if not result["available"]:
        result["detail"] = "thiếu aapt2"
        return result
    result["attempted"] = True
    run = _run_command(["aapt2", "dump", "badging", apk_path], timeout=30)
    output = (run.get("stdout", "") + "\n" + run.get("stderr", "")).strip()
    package = _PACKAGE_RE.search(output)
    if package:
        result["package"] = package.group(1)
        result["version_code"] = package.group(2) or None
        result["version_name"] = package.group(3) or None
    for match in _SDK_RE.finditer(output):
        if match.group(1) == "sdkVersion":
            result["min_sdk"] = match.group(2)
        else:
            result["target_sdk"] = match.group(2)
    result["permissions"] = sorted(set(_PERMISSION_RE.findall(output)))
    if run.get("returncode") != 0:
        result["detail"] = _first_line(output) or "aapt2 không đọc được artifact"
    return result


def _verify_signature(apk_path: str) -> Dict[str, Any]:
    """Đọc kết quả apksigner; không ký lại hoặc thay đổi APK."""
    result: Dict[str, Any] = {
        "attempted": False,
        "available": bool(shutil.which("apksigner")),
        "verified": None,
        "schemes": {},
        "certificate_sha256": [],
        "detail": None,
    }
    if not result["available"]:
        result["detail"] = "thiếu apksigner"
        return result
    result["attempted"] = True
    run = _run_command(["apksigner", "verify", "--verbose", "--print-certs", apk_path], timeout=30)
    output = (run.get("stdout", "") + "\n" + run.get("stderr", "")).strip()
    result["verified"] = run.get("returncode") == 0
    for scheme, value in _SCHEME_RE.findall(output):
        result["schemes"][scheme.lower()] = value.lower() == "true"
    result["certificate_sha256"] = sorted({
        item.replace(":", "").lower() for item in _CERT_RE.findall(output)
    })
    if run.get("returncode") != 0:
        result["detail"] = _first_line(output) or "apksigner không xác minh được artifact"
    return result


def _risk(code: str, severity: str, message: str) -> Dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def inspect_artifact(path: str, include_tools: bool = True) -> Dict[str, Any]:
    """Phân tích chỉ đọc một APK/APKS/XAPK/AAB và trả evidence có cấu trúc."""
    artifact_path = os.path.abspath(path)
    if not os.path.isfile(artifact_path):
        raise FileNotFoundError("Không tìm thấy artifact: %s" % path)

    kind = _artifact_kind(artifact_path)
    stat = os.stat(artifact_path)
    report: Dict[str, Any] = {
        "schema": SCHEMA,
        "generated": _now(),
        "artifact": {
            "path": artifact_path,
            "name": os.path.basename(artifact_path),
            "kind": kind,
            "size_bytes": stat.st_size,
            "sha256": _sha256(artifact_path),
        },
        "structure": {},
        "android": {},
        "signature": {},
        "tools": collect_tool_capabilities() if include_tools else None,
        "risks": [],
        "next_steps": [],
        "summary": {"verdict": "READY_FOR_TRIAGE", "warnings": 0},
    }
    if kind == "unknown":
        report["risks"].append(_risk(
            "UNSUPPORTED_ARTIFACT", "warning",
            "Đuôi tệp không thuộc APK/APKS/XAPK/AAB; chỉ kiểm kê Zip nếu mở được.",
        ))

    try:
        with zipfile.ZipFile(artifact_path) as zf:
            rows = _zip_rows(zf)
    except (OSError, zipfile.BadZipFile) as exc:
        report["risks"].append(_risk("INVALID_ZIP", "blocker", str(exc)))
        report["summary"] = {"verdict": "BLOCKED", "warnings": 1}
        return report

    names = [row.filename for row in rows]
    dex_entries = sorted(name for name in names if _DEX_RE.search(name))
    manifests = sorted(name for name in names if name.endswith("AndroidManifest.xml"))
    abis, native_count = _library_abis(names)
    signatures = sorted(name for name in names if "/META-INF/" in "/" + name or name.startswith("META-INF/"))
    nested = []
    if kind in {"apks", "xapk"}:
        for row in rows:
            if row.filename.lower().endswith(".apk"):
                nested.append({
                    "name": row.filename,
                    "role": _split_role(row.filename),
                    "size_bytes": row.file_size,
                    "compressed_bytes": row.compress_size,
                })
        nested.sort(key=lambda item: (item["role"] != "base", item["name"]))

    modules: List[str] = []
    if kind == "aab":
        modules = sorted({name.split("/", 1)[0] for name in names if "/" in name})

    report["structure"] = {
        "zip_entries": len(rows),
        "compressed_bytes": sum(row.compress_size for row in rows),
        "uncompressed_bytes": sum(row.file_size for row in rows),
        "manifest_entries": manifests,
        "dex_entries": dex_entries,
        "dex_count": len(dex_entries),
        "multidex": len(dex_entries) > 1,
        "abis": abis,
        "native_library_count": native_count,
        "signature_entries": signatures,
        "nested_apk_count": len(nested),
        "nested_apks": nested[:MAX_NESTED_APK_ROWS],
        "nested_apks_truncated": len(nested) > MAX_NESTED_APK_ROWS,
        "modules": modules,
    }

    if kind == "apk":
        report["android"] = _aapt_badging(artifact_path)
        report["signature"] = _verify_signature(artifact_path)
    else:
        report["android"] = {
            "attempted": False,
            "detail": "Metadata package/SDK cần APK base đã chọn hoặc bundletool.",
        }
        report["signature"] = {
            "attempted": False,
            "detail": "Xác minh chữ ký cần APK đã chọn/đã sinh từ bundle.",
        }

    risks: List[Dict[str, str]] = report["risks"]
    if kind in {"apks", "xapk"}:
        risks.append(_risk(
            "SPLIT_CONTAINER", "warning",
            "Artifact chứa split; không được patch/cài một APK con đơn lẻ nếu thiếu base/config bắt buộc.",
        ))
        if not any(row["role"] == "base" for row in nested):
            risks.append(_risk("BASE_APK_NOT_FOUND", "warning", "Không nhận diện được base APK trong container."))
    if kind == "aab":
        risks.append(_risk(
            "AAB_PUBLISHING_FORMAT", "warning",
            "AAB là publishing format; cần bundletool sinh APK set theo device trước khi kiểm thử/cài đặt.",
        ))
    if len(dex_entries) > 1:
        risks.append(_risk("MULTIDEX", "info", "Có nhiều DEX; target/patch cần ghi rõ classes*.dex hoặc cây smali tương ứng."))
    if native_count:
        risks.append(_risk(
            "NATIVE_CODE", "info",
            "Có thư viện native theo ABI; static Smali-only không bao phủ toàn bộ logic thực thi."))
    if kind == "apk" and report["signature"].get("attempted") and not report["signature"].get("verified"):
        risks.append(_risk("SIGNATURE_VERIFY_FAILED", "warning", "apksigner không xác minh APK trước khi can thiệp."))
    if kind in {"apks", "aab"} and include_tools:
        tools = report["tools"] or {}
        bundletool = next((item for item in tools.get("tools", []) if item["name"] == "bundletool"), None)
        if bundletool and not bundletool.get("available"):
            risks.append(_risk("BUNDLETOOL_MISSING", "warning", "Thiếu bundletool để sinh/cài APK set theo device."))

    warning_count = sum(1 for item in risks if item["severity"] == "warning")
    report["summary"] = {
        "verdict": "READY_WITH_WARNING" if warning_count else "READY_FOR_TRIAGE",
        "warnings": warning_count,
        "blockers": sum(1 for item in risks if item["severity"] == "blocker"),
    }
    if kind == "apk":
        report["next_steps"] = [
            "Chạy static triage trước khi chọn patch.",
            "Nếu cần sửa Smali/resource: apk-prepare -> preflight -> transaction -> build -> verify.",
            "Chỉ dùng fast path khi byte/chuỗi target khớp chính xác.",
        ]
    elif kind in {"apks", "xapk", "aab"}:
        report["next_steps"] = [
            "Xác định base/feature/config và thiết bị đích trước khi sửa.",
            "Dùng bundletool hoặc installer hỗ trợ split để tạo/cài APK set hoàn chỉnh.",
            "Sau khi có APK base phù hợp, chạy lại intake rồi mới vào static triage.",
        ]
    else:
        report["next_steps"] = ["Chuyển artifact về APK/APKS/XAPK/AAB hợp lệ trước khi tiếp tục."]
    return report


def render_capabilities_markdown(capabilities: Dict[str, Any]) -> str:
    lines = ["# Tool capabilities", "", "| Công cụ | Có | Phiên bản |", "|---|---:|---|"]
    for row in capabilities.get("tools", []):
        lines.append("| `%s` | %s | %s |" % (
            row["name"], "Có" if row.get("available") else "Thiếu",
            (row.get("version") or row.get("detail") or "—").replace("|", "\\|"),
        ))
    summary = capabilities.get("summary", {})
    lines.extend(["", "- Có: %s/%s" % (summary.get("available", 0), summary.get("total", 0))])
    if summary.get("missing"):
        lines.append("- Thiếu: %s" % ", ".join(summary["missing"]))
    return "\n".join(lines) + "\n"


def render_intake_markdown(report: Dict[str, Any]) -> str:
    artifact = report["artifact"]
    structure = report.get("structure", {})
    android = report.get("android", {})
    signature = report.get("signature", {})
    lines = [
        "# Báo cáo tiếp nhận artifact Android", "",
        "## Artifact", "",
        "| Trường | Giá trị |", "|---|---|",
        "| Tên | `%s` |" % artifact["name"],
        "| Loại | `%s` |" % artifact["kind"],
        "| Kích thước | %d bytes |" % artifact["size_bytes"],
        "| SHA-256 | `%s` |" % artifact["sha256"],
        "| Verdict | **%s** |" % report.get("summary", {}).get("verdict", "UNKNOWN"),
        "", "## Cấu trúc", "",
        "- Zip entries: %s" % structure.get("zip_entries", 0),
        "- DEX: %s%s" % (structure.get("dex_count", 0), " (multidex)" if structure.get("multidex") else ""),
        "- ABI: %s" % (", ".join(structure.get("abis", [])) or "không có native lib"),
        "- Native libraries: %s" % structure.get("native_library_count", 0),
        "- Manifest: %s" % (", ".join(structure.get("manifest_entries", [])) or "không thấy"),
    ]
    if structure.get("nested_apk_count"):
        lines.extend(["", "### Split/APK con", "", "| APK | Vai trò | Kích thước |", "|---|---|---:|"])
        for item in structure.get("nested_apks", []):
            lines.append("| `%s` | %s | %d |" % (item["name"], item["role"], item["size_bytes"]))
    if structure.get("modules"):
        lines.extend(["", "- Module AAB: %s" % ", ".join(structure["modules"])])
    lines.extend(["", "## Metadata Android", ""])
    if android.get("package"):
        lines.extend([
            "- Package: `%s`" % android["package"],
            "- Version: %s (%s)" % (android.get("version_name") or "—", android.get("version_code") or "—"),
            "- SDK: min=%s, target=%s" % (android.get("min_sdk") or "—", android.get("target_sdk") or "—"),
        ])
    else:
        lines.append("- %s" % (android.get("detail") or "Không lấy được metadata."))
    lines.extend(["", "## Chữ ký", ""])
    if signature.get("attempted"):
        lines.append("- apksigner verify: %s" % ("PASS" if signature.get("verified") else "FAIL"))
        if signature.get("schemes"):
            lines.append("- Scheme: %s" % ", ".join("%s=%s" % (k, v) for k, v in sorted(signature["schemes"].items())))
        if signature.get("certificate_sha256"):
            lines.append("- Certificate SHA-256: `%s`" % "`, `".join(signature["certificate_sha256"]))
    else:
        lines.append("- %s" % (signature.get("detail") or "Chưa xác minh."))
    lines.extend(["", "## Cảnh báo / evidence", ""])
    risks = report.get("risks", [])
    if not risks:
        lines.append("- Không có cảnh báo cấu trúc từ intake.")
    for item in risks:
        lines.append("- **%s** `%s`: %s" % (item["severity"], item["code"], item["message"]))
    lines.extend(["", "## Bước tiếp theo", ""])
    for step in report.get("next_steps", []):
        lines.append("1. %s" % step)
    return "\n".join(lines) + "\n"


def _safe_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "artifact"


def write_capabilities(capabilities: Dict[str, Any], out_dir: str) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "tool_capabilities.json")
    md_path = os.path.join(out_dir, "tool_capabilities.md")
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(capabilities, fh, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_capabilities_markdown(capabilities))
    return {"json": json_path, "markdown": md_path}


def run_intake(path: str, out_dir: str, include_tools: bool = True) -> Dict[str, Any]:
    """Tạo report JSON/Markdown và capability snapshot cho một artifact."""
    report = inspect_artifact(path, include_tools=include_tools)
    os.makedirs(out_dir, exist_ok=True)
    stem = _safe_stem(report["artifact"]["name"])
    json_path = os.path.join(out_dir, "intake_%s.json" % stem)
    md_path = os.path.join(out_dir, "intake_%s.md" % stem)
    outputs: Dict[str, Any] = {"json": json_path, "markdown": md_path}
    if include_tools and report.get("tools"):
        outputs["capabilities"] = write_capabilities(report["tools"], out_dir)
    report["outputs"] = outputs
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_intake_markdown(report))
    return report
