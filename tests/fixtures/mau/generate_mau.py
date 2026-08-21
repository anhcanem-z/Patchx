# -*- coding: utf-8 -*-
"""Sinh bộ fixture mẫu trong tests/fixtures/mau/.

Chạy:  python3 tests/fixtures/mau/generate_mau.py

Tạo ra:
  - libdemo64.so  : ELF64 ET_DYN giả, .rodata chứa 2 chuỗi (cho rodata_patcher,
                    rodata_bypass, smart-scan .so)
  - libdemo32.so  : ELF32 giả, .rodata chứa 1 chuỗi
  - smali_tree/   : cây APK giả lập nhỏ (start_scan, smart_scanner, apply)
  - patch_mau.zip : patch zip mẫu kiểu ADD_FILES + MATCH_REPLACE (parser/audit)

Các ELF được dựng theo đúng layout mà test rodata_patcher/rodata_bypass đang
tự dựng trong TMP — nên dùng được trực tiếp, không cần sửa kỳ vọng của test.
"""

import os
import struct
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

S0 = "https://api.old-server.com/v1"
S1 = "https://config.example.com/patchx.json"

PATCH_TEXT = (
    "[MIN_ENGINE_VER]\n1\n[/MIN_ENGINE_VER]\n"
    "[AUTHOR]\nMau\n[/AUTHOR]\n"
    "[PACKAGE]\ncom.demo\n[/PACKAGE]\n"
    "[ADD_FILES]\nSOURCE:\nsave.smali\nTARGET:\nsmali/save.smali\n"
    "[/ADD_FILES]\n"
    "[MATCH_REPLACE]\nTARGET:\n[LAUNCHER_ACTIVITIES]\nMATCH:\n"
    "onCreate\nREGEX:\nfalse\nREPLACE:\nLsave;->m()V\n[/MATCH_REPLACE]\n")

SAVE_SMALI = (
    ".class public Lsave;\n"
    ".super Ljava/lang/Object;\n"
    ".method public static m()V\n"
    "    return-void\n"
    ".end method\n")


def build_elf64(path, strings):
    """ELF64 ET_DYN giả — section .rodata tại RVA 0x1000."""
    rodata_off = 0x1000
    shstr_off = 0x300
    shoff = 0x200
    rodata = b"".join(s.encode("utf-8") + b"\x00" for s in strings)
    rodata += b"\x00" * (0x200 - len(rodata))
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    header = struct.pack(
        "<16sHHIQQQIHHHHHH", ident, 3, 183, 1, 0, 0x40, shoff,
        0, 64, 56, 1, 64, 3, 2)
    phdr = struct.pack("<IIQQQQQQ", 1, 4, rodata_off, rodata_off,
                       rodata_off, len(rodata), len(rodata), 0x1000)
    shstr = b"\x00.shstrtab\x00.rodata\x00"
    sh_null = b"\x00" * 64
    sh_rodata = struct.pack("<IIQQQQIIQQ", 11, 1, 0x2, rodata_off,
                            rodata_off, len(rodata), 0, 0, 1, 0)
    sh_shstr = struct.pack("<IIQQQQIIQQ", 1, 3, 0, 0, shstr_off,
                           len(shstr), 0, 0, 1, 0)
    blob = bytearray(rodata_off)
    blob[0:64] = header
    blob[0x40:0x40 + 56] = phdr
    blob[shoff:shoff + 192] = sh_null + sh_rodata + sh_shstr
    blob[shstr_off:shstr_off + len(shstr)] = shstr
    blob[rodata_off:rodata_off + len(rodata)] = rodata
    with open(path, "wb") as fh:
        fh.write(bytes(blob))


def build_elf32(path, s):
    """ELF32 ET_DYN giả — section .rodata tại RVA 0x1000."""
    rodata_off = 0x1000
    shstr_off = 0x300
    shoff = 0x200
    rodata = s.encode("utf-8") + b"\x00"
    rodata += b"\x00" * (0x200 - len(rodata))
    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\x00" * 8
    header = struct.pack(
        "<16sHHIIIIIHHHHHH", ident, 3, 183, 1, 0, 0x40, shoff,
        0, 52, 32, 1, 40, 3, 2)
    phdr = struct.pack("<IIIIIIII", 1, rodata_off, rodata_off,
                       rodata_off, len(rodata), len(rodata), 4, 0x1000)
    shstr = b"\x00.shstrtab\x00.rodata\x00"
    sh_null = b"\x00" * 40
    sh_rodata = struct.pack("<IIIIIIIIII", 11, 1, 0x2, rodata_off,
                            rodata_off, len(rodata), 0, 0, 1, 0)
    sh_shstr = struct.pack("<IIIIIIIIII", 1, 3, 0, 0, shstr_off,
                           len(shstr), 0, 0, 1, 0)
    blob = bytearray(rodata_off)
    blob[0:52] = header
    blob[0x40:0x40 + 32] = phdr
    blob[shoff:shoff + 120] = sh_null + sh_rodata + sh_shstr
    blob[shstr_off:shstr_off + len(shstr)] = shstr
    blob[rodata_off:rodata_off + len(rodata)] = rodata
    with open(path, "wb") as fh:
        fh.write(bytes(blob))



def build_mini_elf(path, strings):
    """ELF64 tối giản cho start_scan — .rodata tại 0x1000, không .dynsym."""
    rodata_off = 0x1000
    rodata = b"".join(x.encode("utf-8") + b"\x00" for x in strings)
    rodata += b"\x00" * (0x200 - len(rodata))
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    header = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, 183, 1, 0,
                         0x40, 0x200, 0, 64, 56, 1, 64, 3, 2)
    phdr = struct.pack("<IIQQQQQQ", 1, 7, 0, 0, 0, 0x2000, 0x2000, 0x1000)
    shstr = b"\x00.shstrtab\x00.rodata\x00"
    sh_ro = struct.pack("<IIQQQQIIQQ", 11, 1, 0x2, rodata_off,
                        rodata_off, len(rodata), 0, 0, 1, 0)
    sh_st = struct.pack("<IIQQQQIIQQ", 1, 3, 0, 0, 0x180,
                        len(shstr), 0, 0, 1, 0)
    blob = bytearray(0x2000)
    blob[0:64] = header
    blob[0x40:0x40 + 56] = phdr
    blob[0x180:0x180 + len(shstr)] = shstr
    blob[0x1000:0x1000 + len(rodata)] = rodata
    blob[0x200:0x200 + 192] = b"\x00" * 64 + sh_ro + sh_st
    with open(path, "wb") as fh:
        fh.write(bytes(blob))


def build_smart_elf(path, rodata_strings):
    """ELF64 ARM64 cho smart_scanner: .text chứa ADRP+ADD (str1) + LDR
    literal (str2) + .dynsym có hàm JNI bao phủ vùng mã + .rodata chứa
    chuỗi. Layout khớp kỳ vọng test_smart_scanner (str1_rva=0x1000)."""
    shstr_names = [".shstrtab", ".dynsym", ".dynstr", ".text", ".rodata"]
    shstr = b"\x00"
    sh_off = {"": 0}
    for n in shstr_names:
        sh_off[n] = len(shstr)
        shstr += n.encode() + b"\x00"

    dyn_names = ["Java_com_example_App_nativeCheck",
                 "_GLOBAL__sub_I_app"]
    dynstr = b"\x00"
    dyn_off = {}
    for n in dyn_names:
        dyn_off[n] = len(dynstr)
        dynstr += n.encode() + b"\x00"

    rodata = bytearray(0x200)
    ro_off = 0x1000
    for s in rodata_strings:
        rodata[ro_off - 0x1000:ro_off - 0x1000 + len(s)] = s.encode() + b"\x00"
        ro_off += len(s) + 1

    s1, s2 = rodata_strings[0], rodata_strings[1]
    str1_rva = 0x1000
    str2_rva = str1_rva + len(s1) + 1

    # .text: ADRP x0,#page(0x1000); ADD x0,x0,#0; LDR x1,#pool; RET
    text = bytearray(0x100)
    text[0x00:0x04] = struct.pack("<I", 0x90000000 | (1 << 29))
    text[0x04:0x08] = struct.pack("<I", 0x91000000)
    text[0x08:0x0C] = struct.pack("<I", 0x58000000 | (0x2E << 5) | 1)
    text[0x0C:0x10] = struct.pack("<I", 0xD65F03C0)
    text[0xC0:0xC8] = struct.pack("<Q", str2_rva)

    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    header = struct.pack("<16sHHIQQQIHHHHHH", ident, 3, 183, 1, 0,
                         0x40, 0x2000, 0, 64, 56, 1, 64, 6, 1)
    phdr = struct.pack("<IIQQQQQQ", 1, 7, 0, 0, 0, 0x2000, 0x2000, 0x1000)

    def sh(name, stype, flags, addr, off, size, link=0, entsize=0):
        return struct.pack("<IIQQQQIIQQ", sh_off[name], stype, flags,
                           addr, off, size, link, 0, 1, entsize)

    shdrs = b"".join([
        b"\x00" * 64,
        sh(".shstrtab", 3, 0, 0, 0x200, len(shstr)),
        sh(".dynsym", 11, 0x2, 0x400, 0x400, 3 * 24, 3, 24),
        sh(".dynstr", 3, 0x2, 0x300, 0x300, len(dynstr)),
        sh(".text", 1, 0x6, 0x800, 0x800, len(text)),
        sh(".rodata", 1, 0x2, 0x1000, 0x1000, len(rodata)),
    ])

    def sym(name, value, size):
        return struct.pack("<IBBHQQ", dyn_off[name], 0x12, 0, 4,
                           value, size)

    dynsym = b"\x00" * 24 + sym(dyn_names[0], 0x800, 0x20) \
        + sym(dyn_names[1], 0x900, 0x10)

    blob = bytearray(0x2000)
    blob[0:64] = header
    blob[0x40:0x40 + 56] = phdr
    blob[0x200:0x200 + len(shstr)] = shstr
    blob[0x300:0x300 + len(dynstr)] = dynstr
    blob[0x400:0x400 + len(dynsym)] = dynsym
    blob[0x800:0x800 + len(text)] = text
    blob[0x1000:0x1000 + len(rodata)] = rodata
    blob[0x2000:0x2000 + len(shdrs)] = shdrs
    with open(path, "wb") as fh:
        fh.write(bytes(blob))

def write_smali_tree(root):
    """Cây APK giả lập nhỏ — tương thích validate_tree / start_scan."""
    smali = os.path.join(root, "smali", "com", "demo")
    os.makedirs(smali, exist_ok=True)
    manifest = os.path.join(root, "AndroidManifest.xml")
    with open(manifest, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<manifest xmlns:android="http://schemas.android.com/apk/'
                 'res/android" package="com.demo">\n'
                 '  <application android:name=".App">\n'
                 '    <activity android:name=".MainActivity">\n'
                 '      <intent-filter>\n'
                 '        <action android:name="android.intent.action.MAIN"/>\n'
                 '        <category android:name="android.intent.category.LAUNCHER"/>\n'
                 '      </intent-filter>\n'
                 '    </activity>\n'
                 '  </application>\n'
                 '</manifest>\n')
    with open(os.path.join(root, "apktool.yml"), "w", encoding="utf-8") as fh:
        fh.write("!!brut.androlib.meta.MetaInfo\n"
                 "apkFileName: mau.apk\n"
                 "isFrameworkApk: false\n"
                 "packageInfo:\n"
                 "  forcedPackageId: '127'\n"
                 "  renameManifestPackage: null\n"
                 "sdkInfo:\n"
                 "  minSdkVersion: '21'\n"
                 "  targetSdkVersion: '33'\n")
    with open(os.path.join(smali, "MainActivity.smali"), "w",
              encoding="utf-8") as fh:
        fh.write(".class public Lcom/demo/MainActivity;\n\n"
                 ".method protected onCreate(Landroid/os/Bundle;)V\n"
                 "    .registers 5\n\n"
                 "    return-void\n"
                 ".end method\n")
    with open(os.path.join(smali, "Util.smali"), "w", encoding="utf-8") as fh:
        fh.write(".class public Lcom/demo/Util;\n"
                 "const-string v0, \"com.example\"\n"
                 "return-void\n")


def write_patch_zip(zpath, text, assets):
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("patch.txt", text)
        for name, content in (assets or {}).items():
            zf.writestr(name, content)


def main():
    os.makedirs(HERE, exist_ok=True)
    build_elf64(os.path.join(HERE, "libdemo64.so"), (S0, S1))
    build_elf32(os.path.join(HERE, "libdemo32.so"), S0)
    build_elf64(os.path.join(HERE, "libdup.so"), (S0, S0, S1))
    build_smart_elf(os.path.join(HERE, "libsmart.so"), (
        "https://api.old-server.com/v1",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "[INFO] request handled ok",
        "example.com",
        "map::at:  key not found",
    ))
    build_mini_elf(os.path.join(HERE, "libmini_a.so"),
                   ["https://api.old-server.com/v1", "[INFO] ok"])
    build_mini_elf(os.path.join(HERE, "libmini_b.so"),
                   ["AKIAIOSFODNN7EXAMPLE", "example.com"])
    build_mini_elf(os.path.join(HERE, "libmini_c.so"),
                   ["https://x86-only.example.com"])
    write_smali_tree(os.path.join(HERE, "smali_tree"))
    patch_dir = os.path.join(HERE, "patch_mau")
    os.makedirs(patch_dir, exist_ok=True)
    with open(os.path.join(patch_dir, "patch.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(PATCH_TEXT)
    with open(os.path.join(patch_dir, "save.smali"), "w",
              encoding="utf-8") as fh:
        fh.write(SAVE_SMALI)
    write_patch_zip(os.path.join(HERE, "patch_mau.zip"), PATCH_TEXT,
                    {"save.smali": SAVE_SMALI})
    print("Da sinh fixture mau tai:", HERE)


if __name__ == "__main__":
    main()
