# -*- coding: utf-8 -*-
"""Chuẩn bị dữ liệu signature cho patch Java/native; hỗ trợ Multi-Layer Signature Spoofing."""

import hashlib
import json
import os


def extract_cert_hex(apk_path):
    """Trích xuất chuỗi DER certificate v1 dạng hex từ APK gốc."""
    from patchx_toolkit import _extract_apk_cert_hex

    value = _extract_apk_cert_hex(apk_path)
    if not value:
        raise ValueError("APK không có cert v1 PKCS#7 đọc được: %s" % apk_path)
    return value.upper()


def is_valid_der_cert(der_bytes):
    """Kiểm tra sơ bộ tính hợp lệ của khối DER X.509/PKCS#7 (bắt đầu bằng tag ASN.1 SEQUENCE 0x30)."""
    if not der_bytes or len(der_bytes) < 32:
        return False
    return der_bytes[0] == 0x30


def signature_context(apk_path):
    """Tạo context chữ ký gốc đầy đủ (DER, SHA-256, độ dài, biến môi trường)."""
    cert_hex = extract_cert_hex(apk_path)
    der = bytes.fromhex(cert_hex)
    if not is_valid_der_cert(der):
        raise ValueError("Dữ liệu cert trích xuất không phải DER hợp lệ (thiếu ASN.1 SEQUENCE)")

    sha256_hash = hashlib.sha256(der).hexdigest().upper()
    return {
        "apk": apk_path,
        "cert_der_hex": cert_hex,
        "cert_bytes": len(der),
        "sha256": sha256_hash,
        "env": {"PATCHX_RSA_DATA": cert_hex},
    }


def inject_spoof_to_env(apk_path):
    """Tự động nạp chứng chỉ gốc vào biến môi trường PATCHX_RSA_DATA để engine thay %RSA_DATA%."""
    ctx = signature_context(apk_path)
    os.environ["PATCHX_RSA_DATA"] = ctx["cert_der_hex"]
    return ctx


def write_context(apk_path, output):
    """Ghi context chữ ký ra file JSON."""
    ctx = signature_context(apk_path)
    out_dir = os.path.dirname(os.path.abspath(output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(ctx, fh, ensure_ascii=False, indent=2)
    return ctx
