# -*- coding: utf-8 -*-
"""Chuẩn bị dữ liệu signature cho patch Java/native; hỗ trợ Multi-Layer Signature Spoofing (Modder Hub).

Hỗ trợ:
- Trích xuất cert DER v1 hex và SHA-256 từ APK gốc.
- Xác thực định dạng ASN.1 DER SEQUENCE (0x30).
- Nạp cert hex vào biến môi trường PATCHX_RSA_DATA cho engine Smali.
- Sinh script Frida hook đa tầng (Java PackageManager + Signature toByteArray).
- Quét và vá chuỗi SHA-256 cert hash trực tiếp trong phân vùng .rodata của thư viện Native .so.
- Pipeline tích hợp 1-Click: Multi-Layer Signature Spoofing (Java + Native + Frida).
"""

import glob
import hashlib
import json
import os
from typing import Any, Dict, List, Optional


def extract_cert_hex(apk_path: str) -> str:
    """Trích xuất chuỗi DER certificate v1 dạng hex từ APK gốc."""
    from patchx_toolkit import _extract_apk_cert_hex

    value = _extract_apk_cert_hex(apk_path)
    if not value:
        raise ValueError("APK không có cert v1 PKCS#7 đọc được: %s" % apk_path)
    return value.upper()


def is_valid_der_cert(der_bytes: bytes) -> bool:
    """Kiểm tra sơ bộ tính hợp lệ của khối DER X.509/PKCS#7 (bắt đầu bằng tag ASN.1 SEQUENCE 0x30)."""
    if not der_bytes or len(der_bytes) < 32:
        return False
    return der_bytes[0] == 0x30


def signature_context(apk_path: str) -> Dict[str, Any]:
    """Tạo context chữ ký gốc đầy đủ (DER, SHA-256, độ dài, biến môi trường)."""
    cert_hex = extract_cert_hex(apk_path)
    der = bytes.fromhex(cert_hex)
    if not is_valid_der_cert(der):
        raise ValueError("Dữ liệu cert trích xuất không phải DER hợp lệ (thiếu ASN.1 SEQUENCE)")

    sha256_hash = hashlib.sha256(der).hexdigest().upper()
    sha1_hash = hashlib.sha1(der).hexdigest().upper()
    return {
        "apk": apk_path,
        "cert_der_hex": cert_hex,
        "cert_bytes": len(der),
        "sha256": sha256_hash,
        "sha1": sha1_hash,
        "env": {"PATCHX_RSA_DATA": cert_hex},
    }


def inject_spoof_to_env(apk_path: str) -> Dict[str, Any]:
    """Tự động nạp chứng chỉ gốc vào biến môi trường PATCHX_RSA_DATA để engine thay %RSA_DATA%."""
    ctx = signature_context(apk_path)
    os.environ["PATCHX_RSA_DATA"] = ctx["cert_der_hex"]
    return ctx


def generate_java_signature_hook(cert_hex: str) -> str:
    """Sinh mã JavaScript Frida giả lập chữ ký gốc ở tầng Java (PackageManager/PackageInfo)."""
    script = """// == PatchX Multi-Layer Signature Spoof (Java Layer) ==
Java.perform(function() {
    try {
        var certHex = "%CERT_HEX%";
        var Signature = Java.use("android.content.pm.Signature");
        var fakeSig = Signature.$new(certHex);

        var PackageManager = Java.use("android.app.ApplicationPackageManager");
        PackageManager.getPackageInfo.overload("java.lang.String", "int").implementation = function(pkg, flags) {
            var pi = this.getPackageInfo(pkg, flags);
            var GET_SIGNATURES = 64;
            if ((flags & GET_SIGNATURES) !== 0 && pi.signatures) {
                var sigArray = Java.array("android.content.pm.Signature", [fakeSig]);
                pi.signatures.value = sigArray;
            }
            return pi;
        };

        // Spoof getPackageInfo Flags API 28+ (signingInfo)
        try {
            var GET_SIGNING_CERTIFICATES = 134217728;
            PackageManager.getPackageInfo.overload("java.lang.String", "android.content.pm.PackageManager$PackageInfoFlags").implementation = function(pkg, flags) {
                var pi = this.getPackageInfo(pkg, flags);
                if (pi.signatures) {
                    pi.signatures.value = Java.array("android.content.pm.Signature", [fakeSig]);
                }
                return pi;
            };
        } catch(e28) {}

        console.log("[PatchX] Java Signature Spoof active (Cert len: " + (certHex.length/2) + " bytes)");
    } catch(err) {
        console.error("[PatchX] Java Signature Spoof error: " + err);
    }
});
""".replace("%CERT_HEX%", cert_hex)
    return script


def scan_and_spoof_native_library(
    so_path: str,
    target_hash: str,
    replacement_hash: str,
    backup: bool = True,
    out_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Quét và vá chuỗi hash chữ ký trong file .so nhị phân in-place (Native Layer)."""
    if not os.path.isfile(so_path):
        raise FileNotFoundError("Không tìm thấy tệp: %s" % so_path)

    t_upper = target_hash.strip().upper().encode("ascii")
    t_lower = target_hash.strip().lower().encode("ascii")
    r_upper = replacement_hash.strip().upper().encode("ascii")
    r_lower = replacement_hash.strip().lower().encode("ascii")

    if len(r_upper) != len(t_upper):
        raise ValueError("Độ dài replacement hash phải bằng target hash (%d != %d)" % (len(r_upper), len(t_upper)))

    with open(so_path, "rb") as fh:
        raw = bytearray(fh.read())

    hits = 0
    # Thử tìm dạng hoa
    c_up = raw.count(t_upper)
    if c_up > 0:
        raw = raw.replace(t_upper, r_upper)
        hits += c_up

    # Thử tìm dạng thường
    c_low = raw.count(t_lower)
    if c_low > 0:
        raw = raw.replace(t_lower, r_lower)
        hits += c_low

    backup_file = None
    if hits > 0:
        if backup:
            backup_file = so_path + ".bak"
            with open(backup_file, "wb") as bfh:
                with open(so_path, "rb") as src:
                    bfh.write(src.read())
        dest = out_path or so_path
        with open(dest, "wb") as dfh:
            dfh.write(raw)

    return {
        "so": so_path,
        "hits": hits,
        "backup": backup_file,
        "patched": hits > 0,
    }


def multi_layer_spoof_pipeline(
    original_apk: str,
    so_dir: Optional[str] = None,
    new_cert_apk: Optional[str] = None,
    frida_script_out: Optional[str] = None,
) -> Dict[str, Any]:
    """Luồng khép kín Multi-Layer Signature Spoofing (Java + Native + Frida)."""
    ctx = signature_context(original_apk)
    inject_spoof_to_env(original_apk)

    frida_script = generate_java_signature_hook(ctx["cert_der_hex"])
    if frida_script_out:
        os.makedirs(os.path.dirname(os.path.abspath(frida_script_out)), exist_ok=True)
        with open(frida_script_out, "w", encoding="utf-8") as fh:
            fh.write(frida_script)

    native_results = []
    if so_dir and os.path.isdir(so_dir) and new_cert_apk and os.path.isfile(new_cert_apk):
        new_ctx = signature_context(new_cert_apk)
        # Thay thế SHA-256 hash của APK mới bằng SHA-256 hash của APK gốc trong các file .so
        for so_file in glob.glob(os.path.join(so_dir, "**", "*.so"), recursive=True):
            res = scan_and_spoof_native_library(
                so_file,
                target_hash=new_ctx["sha256"],
                replacement_hash=ctx["sha256"],
                backup=True,
            )
            if res["hits"] > 0:
                native_results.append(res)

    return {
        "apk": original_apk,
        "sha256": ctx["sha256"],
        "sha1": ctx["sha1"],
        "cert_bytes": ctx["cert_bytes"],
        "env_injected": "PATCHX_RSA_DATA",
        "frida_script": frida_script_out,
        "native_patches": native_results,
    }


def write_context(apk_path: str, output: str) -> Dict[str, Any]:
    """Ghi context chữ ký ra file JSON."""
    ctx = signature_context(apk_path)
    out_dir = os.path.dirname(os.path.abspath(output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(ctx, fh, ensure_ascii=False, indent=2)
    return ctx
