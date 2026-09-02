# -*- coding: utf-8 -*-
"""Bộ kiểm thử cho 5 module kế thừa và tối ưu từ Modder Hub:
1. dex_inplace.py (DEX Bytecode & Header in-place patching)
2. axml_editor.py (Binary AXML/ARSC chunk & string pool editor)
3. signature_spoof.py (Multi-layer signature context & spoofing)
4. apk_fast_repack.py (Zero-copy in-place repacking & fast-patch)
5. macro_registry.py (Smali macro registry & register validation)
"""

import os
import shutil
import struct
import tempfile
import zipfile

from patchx_core.dex_inplace import (
    DexHeader,
    recalculate_dex_checksums,
    inspect_dex,
    replace_string_inline,
    replace_bytecode_pattern,
    patch_dex_file_strings,
    patch_dex_file_bytecode,
    FORCE_TRUE_V0,
    FORCE_FALSE_V0,
    RETURN_VOID,
    OP_NOP,
)
from patchx_core.axml_editor import (
    inspect_chunks,
    inspect_string_pool,
    inspect_binary,
    replace_string_inplace,
    RES_XML_TYPE,
    RES_STRING_POOL_TYPE,
)
from patchx_core.signature_spoof import (
    is_valid_der_cert,
    signature_context,
    inject_spoof_to_env,
    extract_cert_hex,
)
from patchx_core.apk_fast_repack import (
    is_signature_entry,
    fast_repack_apk,
    fast_patch_and_repack,
)
from patchx_core.macro_registry import (
    list_macros,
    get_macro,
    required_registers,
    validate_macro,
)


def make_dummy_dex(content=b""):
    """Tạo một buffer DEX hợp lệ với 112 bytes header và nội dung tùy chọn."""
    total_len = 112 + len(content)
    hdr = bytearray(112)
    hdr[0:8] = b"dex\n035\0"
    struct.pack_into("<I", hdr, 32, total_len)  # file_size
    raw = bytes(hdr) + content
    return recalculate_dex_checksums(raw)


def run_all_modder_hub_tests(check_fn):
    """Chạy toàn bộ các test case cho nhóm module Modder Hub fast-path."""

    # ==================== 1. DEX IN-PLACE ====================
    dex_valid = make_dummy_dex(b"SampleStringHere\x12\x00\x0f\x00\x00\x00")
    hdr = DexHeader(dex_valid)
    check_fn("dex: parse header magic", hdr.magic == b"dex\n035\0")

    info = inspect_dex(dex_valid)
    check_fn("dex: inspect header dict", "magic" in info and info["file_size"] == len(dex_valid))

    try:
        DexHeader(b"too_short")
        check_fn("dex: short buffer check", False, "không ném lỗi khi buffer ngắn")
    except ValueError:
        check_fn("dex: short buffer check", True)

    try:
        DexHeader(b"badmagic" + b"\x00" * 104)
        check_fn("dex: bad magic check", False, "không ném lỗi khi magic sai")
    except ValueError:
        check_fn("dex: bad magic check", True)

    # String inline replace
    patched_str, cnt = replace_string_inline(dex_valid, "SampleStringHere", "ShortString")
    check_fn("dex: replace string inline hit", cnt == 1)
    check_fn("dex: string padded with null", b"ShortString\x00\x00\x00\x00\x00" in patched_str)

    try:
        replace_string_inline(dex_valid, "SampleStringHere", "VeryLongStringExceedingLimit")
        check_fn("dex: reject longer string", False, "không chặn chuỗi dài hơn")
    except ValueError:
        check_fn("dex: reject longer string", True)

    # Bytecode replace (6 bytes -> 4 bytes FORCE_TRUE + 2 bytes NOP)
    patched_bc, bcnt = replace_bytecode_pattern(dex_valid, b"\x12\x00\x0f\x00\x00\x00", FORCE_TRUE_V0)
    check_fn("dex: replace bytecode hit", bcnt == 1)
    check_fn("dex: bytecode padded with nop", (FORCE_TRUE_V0 + OP_NOP) in patched_bc)

    # Hex string pattern
    patched_hex, hcnt = replace_bytecode_pattern(dex_valid, "12000f000000", "12100f00")
    check_fn("dex: replace hex bytecode hit", hcnt == 1)

    # File-level patch
    with tempfile.TemporaryDirectory() as td:
        dex_file = os.path.join(td, "classes.dex")
        with open(dex_file, "wb") as fh:
            fh.write(dex_valid)
        res_f = patch_dex_file_strings(dex_file, [("SampleStringHere", "PatchedFileStr")], backup_dir=os.path.join(td, "bak"))
        check_fn("dex: patch_dex_file_strings hit", res_f["total_replaced"] == 1)
        check_fn("dex: patch_dex_file_strings backup exists", os.path.isfile(os.path.join(td, "bak", "classes.dex.bak")))

        res_bc = patch_dex_file_bytecode(dex_file, [(b"\x12\x00\x0f\x00\x00\x00", RETURN_VOID)], backup_dir=None)
        check_fn("dex: patch_dex_file_bytecode hit", res_bc["total_replaced"] == 1)

    # ==================== 2. AXML EDITOR ====================
    # Tạo dummy AXML nhị phân (Root RES_XML 0x0003 bọc String Pool 0x0001)
    str_utf8 = b"AppNameOriginal"
    sp_chunk = struct.pack("<HHIIIIII", RES_STRING_POOL_TYPE, 28, 28 + len(str_utf8), 1, 0, 0x100, 28, 0) + str_utf8
    root_chunk = struct.pack("<HHI", RES_XML_TYPE, 8, 8 + len(sp_chunk)) + sp_chunk

    chunks = inspect_chunks(root_chunk, recurse_containers=True)
    check_fn("axml: inspect_chunks recurse container", len(chunks) == 2)
    check_fn("axml: root chunk type", chunks[0]["type"] == RES_XML_TYPE)
    check_fn("axml: child chunk type", chunks[1]["type"] == RES_STRING_POOL_TYPE)

    sp_info = inspect_string_pool(root_chunk)
    check_fn("axml: inspect_string_pool detect utf-8", sp_info is not None and sp_info["is_utf8"] is True)

    with tempfile.TemporaryDirectory() as td:
        xml_file = os.path.join(td, "AndroidManifest.xml")
        with open(xml_file, "wb") as fh:
            fh.write(root_chunk)

        res_xml_u8 = replace_string_inplace(xml_file, "AppNameOriginal", "AppNameModded")
        check_fn("axml: replace_string_inplace utf-8 hit", res_xml_u8["hits"] == 1 and res_xml_u8["encoding"] == "utf-8")

        # Test UTF-16LE binary XML
        u16_str = "UnicodePackageName".encode("utf-16le")
        sp_u16 = struct.pack("<HHIIIIII", RES_STRING_POOL_TYPE, 28, 28 + len(u16_str), 1, 0, 0x0, 28, 0) + u16_str
        root_u16 = struct.pack("<HHI", RES_XML_TYPE, 8, 8 + len(sp_u16)) + sp_u16

        xml_u16_file = os.path.join(td, "AndroidManifest_u16.xml")
        with open(xml_u16_file, "wb") as fh:
            fh.write(root_u16)

        res_xml_u16 = replace_string_inplace(xml_u16_file, "UnicodePackageName", "ShortName")
        check_fn("axml: replace_string_inplace auto utf-16le hit", res_xml_u16["hits"] == 1 and res_xml_u16["encoding"] == "utf-16le")

    # ==================== 3. SIGNATURE SPOOF ====================
    check_fn("sig: valid DER check on SEQUENCE 0x30", is_valid_der_cert(b"\x30\x82" + b"\x00" * 32))
    check_fn("sig: invalid DER check on short buffer", is_valid_der_cert(b"\x30\x00") is False)
    check_fn("sig: invalid DER check on wrong tag", is_valid_der_cert(b"\x31\x82" + b"\x00" * 32) is False)

    sample_apk = "Apks/Fake GPS_5.8.7_kill.apk"
    if os.path.isfile(sample_apk):
        cert_hex = extract_cert_hex(sample_apk)
        check_fn("sig: extract_cert_hex from real APK", len(cert_hex) > 100)
        ctx = signature_context(sample_apk)
        check_fn("sig: signature_context SHA256", len(ctx["sha256"]) == 64)
        inject_spoof_to_env(sample_apk)
        check_fn("sig: inject_spoof_to_env", os.environ.get("PATCHX_RSA_DATA") == ctx["cert_der_hex"])
    else:
        check_fn("sig: skip real apk test (file missing)", True)

    # ==================== 4. APK FAST REPACK ====================
    check_fn("repack: identify signature file .SF", is_signature_entry("META-INF/CERT.SF"))
    check_fn("repack: identify signature file .RSA", is_signature_entry("META-INF/ANDROID.RSA"))
    check_fn("repack: identify signature file MANIFEST.MF", is_signature_entry("META-INF/MANIFEST.MF"))
    check_fn("repack: normal file not signature", is_signature_entry("res/drawable/icon.png") is False)

    with tempfile.TemporaryDirectory() as td:
        apk_src = os.path.join(td, "dummy.apk")
        apk_out = os.path.join(td, "dummy_out.apk")

        with zipfile.ZipFile(apk_src, "w") as z:
            z.writestr("classes.dex", dex_valid)
            z.writestr("AndroidManifest.xml", "TestTargetString".encode("utf-16le"))
            z.writestr("META-INF/CERT.RSA", b"cert_data")
            z.writestr("res/values/strings.arsc", b"arsc_data")

        # Test fast_repack_apk with strip_signatures
        repack_res = fast_repack_apk(apk_src, {"classes.dex": b"new_dex_data"}, apk_out, strip_signatures=True)
        check_fn("repack: fast_repack_apk success", repack_res["updated_entries"] == 1)
        check_fn("repack: stripped signatures count", repack_res["stripped_signatures"] == 1)

        with zipfile.ZipFile(apk_out, "r") as zout:
            names = zout.namelist()
            check_fn("repack: META-INF/CERT.RSA was stripped", "META-INF/CERT.RSA" not in names)
            check_fn("repack: updated classes.dex content", zout.read("classes.dex") == b"new_dex_data")

        # Test 1-click fast_patch_and_repack
        apk_1click_out = os.path.join(td, "dummy_1click.apk")
        patch_res = fast_patch_and_repack(
            apk_src,
            dex_replacements=[("SampleStringHere", "NewAppString")],
            axml_replacements=[("TestTargetString", "NewTarget")],
            output_apk=apk_1click_out,
            strip_signatures=True,
        )
        check_fn("repack: 1-click fast_patch_and_repack success", patch_res["success"] is True)
        check_fn("repack: 1-click dex hits", patch_res["dex_hits"] == 1)
        check_fn("repack: 1-click axml hits", patch_res["axml_hits"] == 1)

    # ==================== 5. MACRO REGISTRY ====================
    macros = list_macros()
    check_fn("macro: list_macros contains standard macros", "return_true" in macros and "toast_status" in macros)

    r_true = get_macro("return_true")
    check_fn("macro: return_true content", "return v0" in r_true)

    toast = get_macro("toast_status")
    check_fn("macro: toast_status has makeText", "makeText" in toast)

    logcat = get_macro("logcat_interceptor")
    check_fn("macro: logcat_interceptor has NO pop opcode", "pop" not in logcat)

    v_true = validate_macro("return_true", 1)
    check_fn("macro: validate return_true with 1 reg safe", v_true["safe"] is True)

    v_toast_unsafe = validate_macro("toast_status", 0)
    check_fn("macro: validate toast_status with 0 reg unsafe", v_toast_unsafe["safe"] is False)

    v_toast_safe = validate_macro("toast_status", 2)
    check_fn("macro: validate toast_status with 2 reg safe", v_toast_safe["safe"] is True)
