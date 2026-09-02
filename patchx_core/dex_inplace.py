# -*- coding: utf-8 -*-
"""Direct DEX Bytecode & Header Inplace Patching (Kế thừa và nâng cấp từ Modder Hub).

Cho phép can thiệp trực tiếp file `.dex` ở mức nhị phân:
- Đọc và phân tích Header (DEX 035/037/038/039).
- Quét và thay thế chuỗi in-place trong bảng chuỗi / data pool.
- Quét và thay thế bytecode/opcode nhị phân (SET_BOOL, FORCE_TRUE, NOP, RETURN_VOID).
- Tự động tính lại SHA-1 Signature và Adler32 Checksum sau khi sửa đổi.
- Hỗ trợ Fast-Path không cần qua apktool decompile/rebuild.
"""

import hashlib
import os
import shutil
import struct
import zlib

DEX_MAGICS = (
    b"dex\n035\0",
    b"dex\n037\0",
    b"dex\n038\0",
    b"dex\n039\0",
)

# Các mẫu opcode Dalvik chuẩn (16-bit code unit)
OP_NOP = b"\x00\x00"
OP_RETURN_VOID = b"\x0e\x00"
OP_RETURN_V0 = b"\x0f\x00"
OP_CONST_4_V0_1 = b"\x12\x10"  # const/4 v0, 0x1
OP_CONST_4_V0_0 = b"\x12\x00"  # const/4 v0, 0x0
FORCE_TRUE_V0 = b"\x12\x10\x0f\x00"  # const/4 v0, 1; return v0 (4 bytes)
FORCE_FALSE_V0 = b"\x12\x00\x0f\x00"  # const/4 v0, 0; return v0 (4 bytes)
RETURN_VOID = b"\x0e\x00"  # return-void (2 bytes)


class DexHeader:
    """Đại diện cấu trúc DEX Header chuẩn (112 bytes)."""

    def __init__(self, raw_bytes):
        if len(raw_bytes) < 112:
            raise ValueError("Dữ liệu quá ngắn không đủ DEX header (cần >= 112 bytes)")
        self.magic = raw_bytes[0:8]
        if self.magic not in DEX_MAGICS:
            raise ValueError("Magic DEX không hợp lệ: %r" % self.magic)

        (
            self.checksum,
            self.signature,
            self.file_size,
            self.header_size,
            self.endian_tag,
            self.link_size,
            self.link_off,
            self.map_off,
            self.string_ids_size,
            self.string_ids_off,
            self.type_ids_size,
            self.type_ids_off,
            self.proto_ids_size,
            self.proto_ids_off,
            self.field_ids_size,
            self.field_ids_off,
            self.method_ids_size,
            self.method_ids_off,
            self.class_defs_size,
            self.class_defs_off,
            self.data_size,
            self.data_off,
        ) = struct.unpack("<I20s20I", raw_bytes[8:112])


def recalculate_dex_checksums(dex_data):
    """Tính lại SHA-1 (offset 12..32) và Adler32 (offset 8..12) cho DEX bytes."""
    data = bytearray(dex_data)
    if len(data) < 112:
        return bytes(data)

    # 1. SHA-1 signature từ offset 32 đến hết file
    sha1 = hashlib.sha1(data[32:]).digest()
    data[12:32] = sha1

    # 2. Adler32 checksum từ offset 12 đến hết file
    adler = zlib.adler32(data[12:]) & 0xFFFFFFFF
    data[8:12] = struct.pack("<I", adler)

    return bytes(data)


def inspect_dex(dex_bytes):
    """Phân tích cấu trúc cơ bản của buffer DEX nhị phân."""
    hdr = DexHeader(dex_bytes)
    return {
        "magic": hdr.magic.decode("latin-1", errors="replace"),
        "file_size": hdr.file_size,
        "string_ids": hdr.string_ids_size,
        "type_ids": hdr.type_ids_size,
        "method_ids": hdr.method_ids_size,
        "class_defs": hdr.class_defs_size,
        "data_size": hdr.data_size,
    }


def replace_string_inline(dex_bytes, old_str, new_str):
    """Thay thế chuỗi UTF-8 in-place nếu độ dài chuỗi mới <= chuỗi cũ.

    Tự động đệm null bytes và cập nhật checksum/signature.
    """
    if isinstance(old_str, str):
        old_b = old_str.encode("utf-8")
    else:
        old_b = old_str

    if isinstance(new_str, str):
        new_b = new_str.encode("utf-8")
    else:
        new_b = new_str

    if not old_b:
        raise ValueError("Chuỗi cũ không được để trống")

    if len(new_b) > len(old_b):
        raise ValueError(
            "Chuỗi mới (%d bytes) dài hơn chuỗi cũ (%d bytes), không thể sửa in-place."
            % (len(new_b), len(old_b))
        )

    # Đệm byte null cho phần thừa
    padded_new_b = new_b + b"\x00" * (len(old_b) - len(new_b))
    count = dex_bytes.count(old_b)
    if count == 0:
        return dex_bytes, 0

    new_data = dex_bytes.replace(old_b, padded_new_b)
    updated = recalculate_dex_checksums(new_data)
    return updated, count


def _normalize_pattern(pat):
    """Chuyển đổi chuỗi hex hoặc bytes thành bytes."""
    if isinstance(pat, str):
        cleaned = pat.replace(" ", "").replace("0x", "")
        return bytes.fromhex(cleaned)
    return bytes(pat)


def replace_bytecode_pattern(dex_bytes, target_pattern, replacement_pattern, pad_nop=True):
    """Thay thế một chuỗi opcode/bytecode nhị phân in-place trong DEX.

    :param dex_bytes: buffer nhị phân file DEX
    :param target_pattern: chuỗi byte hoặc hex cần tìm
    :param replacement_pattern: chuỗi byte hoặc hex thay thế (phải có len <= target)
    :param pad_nop: nếu True, đệm các cặp byte thừa bằng NOP (0x00 0x00)
    :return: (updated_dex_bytes, hit_count)
    """
    target_b = _normalize_pattern(target_pattern)
    repl_b = _normalize_pattern(replacement_pattern)

    if not target_b:
        raise ValueError("Target pattern không được để trống")

    if len(repl_b) > len(target_b):
        raise ValueError(
            "Replacement (%d bytes) dài hơn target pattern (%d bytes), không thể sửa in-place."
            % (len(repl_b), len(target_b))
        )

    remainder = len(target_b) - len(repl_b)
    if pad_nop and remainder > 0:
        # Trong Dalvik bytecode, các lệnh là bội của 2 bytes (16-bit)
        nop_units = remainder // 2
        extra_bytes = remainder % 2
        padded_repl = repl_b + (OP_NOP * nop_units) + (b"\x00" * extra_bytes)
    else:
        padded_repl = repl_b + (b"\x00" * remainder)

    count = dex_bytes.count(target_b)
    if count == 0:
        return dex_bytes, 0

    new_data = dex_bytes.replace(target_b, padded_repl)
    updated = recalculate_dex_checksums(new_data)
    return updated, count


def patch_dex_file_strings(dex_path, replacements, backup_dir=None):
    """Áp dụng danh sách thay thế chuỗi lên file .dex và cập nhật checksum."""
    if not os.path.isfile(dex_path):
        raise FileNotFoundError("Không tìm thấy tệp DEX: %s" % dex_path)

    with open(dex_path, "rb") as fh:
        raw = fh.read()

    _ = DexHeader(raw)  # validate header

    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        bak = os.path.join(backup_dir, os.path.basename(dex_path) + ".bak")
        shutil.copy2(dex_path, bak)

    curr_bytes = raw
    total_replaced = 0
    details = []

    for old_s, new_s in replacements:
        curr_bytes, n = replace_string_inline(curr_bytes, old_s, new_s)
        total_replaced += n
        details.append({"old": str(old_s), "new": str(new_s), "hits": n})

    with open(dex_path, "wb") as fh:
        fh.write(curr_bytes)

    return {
        "dex_path": dex_path,
        "total_replaced": total_replaced,
        "details": details,
        "new_size": len(curr_bytes),
    }


def patch_dex_file_bytecode(dex_path, replacements, backup_dir=None):
    """Áp dụng danh sách thay thế bytecode/opcode lên file .dex và cập nhật checksum.

    replacements: list of (target_pattern, replacement_pattern)
    """
    if not os.path.isfile(dex_path):
        raise FileNotFoundError("Không tìm thấy tệp DEX: %s" % dex_path)

    with open(dex_path, "rb") as fh:
        raw = fh.read()

    _ = DexHeader(raw)

    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        bak = os.path.join(backup_dir, os.path.basename(dex_path) + ".bak")
        shutil.copy2(dex_path, bak)

    curr_bytes = raw
    total_replaced = 0
    details = []

    for item in replacements:
        target = item[0]
        repl = item[1]
        pad = item[2] if len(item) > 2 else True
        curr_bytes, n = replace_bytecode_pattern(curr_bytes, target, repl, pad_nop=pad)
        total_replaced += n
        details.append({
            "target": target.hex() if isinstance(target, (bytes, bytearray)) else str(target),
            "replacement": repl.hex() if isinstance(repl, (bytes, bytearray)) else str(repl),
            "hits": n,
        })

    with open(dex_path, "wb") as fh:
        fh.write(curr_bytes)

    return {
        "dex_path": dex_path,
        "total_replaced": total_replaced,
        "details": details,
        "new_size": len(curr_bytes),
    }
