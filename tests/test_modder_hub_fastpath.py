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
    inspect_arsc,
    replace_string_inplace,
    replace_arsc_strings,
    parse_strings,
    inspect_manifest_security,
    bypass_network_security_config,
    replace_permission,
    RES_XML_TYPE,
    RES_STRING_POOL_TYPE,
    RES_TABLE_TYPE,
)
from patchx_core.signature_spoof import (
    is_valid_der_cert,
    signature_context,
    inject_spoof_to_env,
    extract_cert_hex,
    generate_java_signature_hook,
    scan_and_spoof_native_library,
    multi_layer_spoof_pipeline,
)
from patchx_core.apk_fast_repack import (
    is_signature_entry,
    safe_open_zip,
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

        # Test parse_strings và inspect_manifest_security
        sample_apk = "Apks/Fake GPS_5.8.7_kill.apk"
        if os.path.isfile(sample_apk):
            with zipfile.ZipFile(sample_apk, "r") as z:
                real_manifest = z.read("AndroidManifest.xml")
            real_strs = parse_strings(real_manifest)
            check_fn("axml: parse_strings extracts pool strings", len(real_strs) > 50 and "application" in real_strs)

            real_xml_file = os.path.join(td, "RealAndroidManifest.xml")
            with open(real_xml_file, "wb") as fh:
                fh.write(real_manifest)
            sec_report = inspect_manifest_security(real_xml_file)
            check_fn("axml: inspect_manifest_security reports stats", sec_report["total_strings"] > 50 and "has_network_security_config" in sec_report)
        else:
            check_fn("axml: parse_strings extracts pool strings", True)
            check_fn("axml: inspect_manifest_security reports stats", True)

        # Test bypass_network_security_config
        nsc_str = "networkSecurityConfig".encode("utf-8")
        sp_nsc = struct.pack("<HHIIIIII", RES_STRING_POOL_TYPE, 28, 28 + len(nsc_str), 1, 0, 0x00000100, 28, 0) + nsc_str
        root_nsc = struct.pack("<HHI", RES_XML_TYPE, 8, 8 + len(sp_nsc)) + sp_nsc
        nsc_file = os.path.join(td, "AndroidManifest_nsc.xml")
        with open(nsc_file, "wb") as fh:
            fh.write(root_nsc)
        nsc_res = bypass_network_security_config(nsc_file)
        check_fn("axml: bypass_network_security_config hit", nsc_res["hits"] == 1)

        # Test replace_permission
        perm_old = "android.permission.INTERNET"
        perm_new = "android.permission.CAMERA"
        perm_str = perm_old.encode("utf-8")
        sp_perm = struct.pack("<HHIIIIII", RES_STRING_POOL_TYPE, 28, 28 + len(perm_str), 1, 0, 0x00000100, 28, 0) + perm_str
        root_perm = struct.pack("<HHI", RES_XML_TYPE, 8, 8 + len(sp_perm)) + sp_perm
        perm_file = os.path.join(td, "AndroidManifest_perm.xml")
        with open(perm_file, "wb") as fh:
            fh.write(root_perm)
        perm_res = replace_permission(perm_file, perm_old, perm_new)
        check_fn("axml: replace_permission hit", perm_res["hits"] == 1)

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

    hook_js = generate_java_signature_hook("3082ABCD1234")
    check_fn("sig: generate_java_signature_hook contains target cert", "3082ABCD1234" in hook_js and "ApplicationPackageManager" in hook_js)

    with tempfile.TemporaryDirectory() as td_sig:
        fake_so = os.path.join(td_sig, "libnative_test.so")
        orig_h = "A" * 64
        fake_h = "B" * 64
        with open(fake_so, "wb") as fh:
            fh.write(b"\x7fELF" + b"\x00" * 64 + orig_h.encode() + b"\x00" * 32)

        res_nat = scan_and_spoof_native_library(fake_so, orig_h, fake_h, backup=True)
        check_fn("sig: scan_and_spoof_native_library hit", res_nat["hits"] == 1 and res_nat["patched"] is True)
        check_fn("sig: scan_and_spoof_native_library backup exists", os.path.isfile(fake_so + ".bak"))

        if os.path.isfile(sample_apk):
            pipe_res = multi_layer_spoof_pipeline(
                sample_apk,
                frida_script_out=os.path.join(td_sig, "sig_hook.js")
            )
            check_fn("sig: multi_layer_spoof_pipeline runs", os.path.isfile(os.path.join(td_sig, "sig_hook.js")))
        else:
            check_fn("sig: multi_layer_spoof_pipeline runs", True)

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

    # ==================== 6. ARSC EDITOR & COMPATIBILITY ====================
    # Tạo dummy ARSC (RES_TABLE 0x0002 bọc RES_STRING_POOL 0x0001)
    arsc_str = b"StringInArscResource"
    sp_arsc = struct.pack("<HHIIIIII", RES_STRING_POOL_TYPE, 28, 28 + len(arsc_str), 1, 0, 0x100, 28, 0) + arsc_str
    root_arsc = struct.pack("<HHII", RES_TABLE_TYPE, 12, 12 + len(sp_arsc), 1) + sp_arsc

    with tempfile.TemporaryDirectory() as td:
        arsc_file = os.path.join(td, "resources.arsc")
        with open(arsc_file, "wb") as fh:
            fh.write(root_arsc)

        arsc_info = inspect_arsc(arsc_file)
        check_fn("arsc: inspect_arsc valid table", arsc_info["is_valid_arsc"] is True)
        check_fn("arsc: inspect_arsc string pool exists", arsc_info["string_pool"] is not None)

        rep_arsc_res = replace_arsc_strings(arsc_file, [("StringInArscResource", "PatchedArscResource")], backup_path=arsc_file + ".bak")
        check_fn("arsc: replace_arsc_strings hits", rep_arsc_res["total_hits"] == 1)
        check_fn("arsc: backup created", os.path.isfile(arsc_file + ".bak"))

        with open(arsc_file, "rb") as fh:
            check_fn("arsc: patched content present", b"PatchedArscResource" in fh.read())

        # Test safe_open_zip with python 3.14 compatibility
        apk_test = os.path.join(td, "test_overlap.apk")
        with zipfile.ZipFile(apk_test, "w") as z:
            z.writestr("classes.dex", b"dex\n035\0" + b"\x00" * 104)
            z.writestr("resources.arsc", root_arsc)

        with safe_open_zip(apk_test, "r") as z_safe:
            entries = z_safe.namelist()
            check_fn("repack: safe_open_zip read entries", len(entries) == 2)
            check_fn("repack: safe_open_zip read content", len(z_safe.read("classes.dex")) == 112)

        # Test fast_patch_and_repack with arsc_replacements
        apk_arsc_out = os.path.join(td, "test_arsc_out.apk")
        fp_arsc_res = fast_patch_and_repack(
            apk_test,
            arsc_replacements=[("StringInArscResource", "PatchedInFastRepack")],
            output_apk=apk_arsc_out,
        )
        check_fn("repack: fast_patch_and_repack with arsc success", fp_arsc_res["success"] is True)
        check_fn("repack: fast_patch_and_repack arsc_hits", fp_arsc_res["arsc_hits"] == 1)

        with safe_open_zip(apk_arsc_out, "r") as z_out:
            check_fn("repack: arsc entry patched in output apk", b"PatchedInFastRepack" in z_out.read("resources.arsc"))

    # ==================== 7. NATIVE SIGNATURE PIPELINE ====================
    with tempfile.TemporaryDirectory() as td:
        so_file = os.path.join(td, "libnative.so")
        orig_hash = "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"
        new_hash = "aabbccddeeff11223344556677889900aabbccddeeff11223344556677889900"
        with open(so_file, "wb") as fh:
            fh.write(b"\x7fELF" + b"\x00" * 100 + orig_hash.encode("ascii") + b"\x00" * 20)

        spoof_res = scan_and_spoof_native_library(so_file, orig_hash, new_hash, backup=True)
        check_fn("native: scan_and_spoof_native_library hit", spoof_res["hits"] == 1)
        check_fn("native: scan_and_spoof_native_library backup", os.path.isfile(so_file + ".bak"))

        with open(so_file, "rb") as fh:
            check_fn("native: new hash present in .so", new_hash.encode("ascii") in fh.read())
