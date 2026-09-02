# -*- coding: utf-8 -*-
"""Bộ thao tác nhị phân an toàn cho AXML và ARSC (Kế thừa và tối ưu từ Modder Hub).

Hỗ trợ:
- Phân tích cấu trúc Chunk (RES_XML_TYPE, RES_STRING_POOL_TYPE, RES_XML_RESOURCE_MAP_TYPE, ...).
- Tự động nhận diện chuỗi String Pool ở cả 2 chuẩn mã hóa UTF-8 và UTF-16LE.
- Thay thế chuỗi nhị phân in-place an toàn với padding null bytes và tạo backup.
"""

import os
import shutil
import struct

# Định nghĩa các loại Chunk Android Binary XML / ARSC chuẩn
RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104
RES_XML_RESOURCE_MAP_TYPE = 0x0180

CHUNK_NAMES = {
    RES_STRING_POOL_TYPE: "RES_STRING_POOL",
    RES_TABLE_TYPE: "RES_TABLE",
    RES_XML_TYPE: "RES_XML",
    RES_XML_START_NAMESPACE_TYPE: "RES_XML_START_NAMESPACE",
    RES_XML_END_NAMESPACE_TYPE: "RES_XML_END_NAMESPACE",
    RES_XML_START_ELEMENT_TYPE: "RES_XML_START_ELEMENT",
    RES_XML_END_ELEMENT_TYPE: "RES_XML_END_ELEMENT",
    RES_XML_CDATA_TYPE: "RES_XML_CDATA",
    RES_XML_RESOURCE_MAP_TYPE: "RES_XML_RESOURCE_MAP",
}


def inspect_chunks(data, recurse_containers=True):
    """Trả danh sách chunk (type, name, offset, header_size, size).

    Nếu recurse_containers=True, duyệt sâu vào các chunk con bên trong container (RES_XML hoặc RES_TABLE).
    """
    out = []
    off = 0

    def _parse_range(start_off, end_off):
        curr = start_off
        while curr + 8 <= end_off:
            typ, header_size, size = struct.unpack_from("<HHI", data, curr)
            if size < 8 or curr + size > end_off:
                break
            name = CHUNK_NAMES.get(typ, "UNKNOWN_0x%04X" % typ)
            item = {
                "type": typ,
                "name": name,
                "offset": curr,
                "header_size": header_size,
                "size": size,
            }
            out.append(item)

            if recurse_containers and typ in (RES_XML_TYPE, RES_TABLE_TYPE) and header_size >= 8:
                # Container chunk bao bọc các sub-chunk con
                sub_start = curr + header_size
                sub_end = curr + size
                _parse_range(sub_start, sub_end)
                curr += size
            else:
                curr += size

    _parse_range(0, len(data))
    return out


def inspect_string_pool(data):
    """Tìm và đọc thông tin metadata của String Pool (chunk 0x0001)."""
    chunks = inspect_chunks(data, recurse_containers=True)
    sp = None
    for c in chunks:
        if c["type"] == RES_STRING_POOL_TYPE:
            sp = c
            break
    if not sp:
        return None

    off = sp["offset"]
    if off + 28 > len(data):
        return None

    _, header_size, size, string_count, style_count, flags, strings_start, styles_start = struct.unpack_from(
        "<HHIIIIII", data, off
    )
    is_utf8 = bool(flags & 0x00000100)
    return {
        "offset": off,
        "size": size,
        "string_count": string_count,
        "style_count": style_count,
        "flags": flags,
        "is_utf8": is_utf8,
        "encoding": "utf-8" if is_utf8 else "utf-16le",
    }


def inspect_binary(path):
    """Kiểm tra tổng quát file nhị phân AXML/ARSC."""
    if not os.path.isfile(path):
        raise FileNotFoundError("Không tìm thấy tệp nhị phân: %s" % path)

    with open(path, "rb") as fh:
        data = fh.read()

    chunks = inspect_chunks(data, recurse_containers=True)
    sp_info = inspect_string_pool(data)
    valid_prefix = len(chunks) > 0 and chunks[0]["type"] in (RES_XML_TYPE, RES_TABLE_TYPE, RES_STRING_POOL_TYPE)

    return {
        "path": path,
        "size": len(data),
        "chunks": chunks,
        "string_pool": sp_info,
        "valid_prefix": valid_prefix,
    }


def replace_string_inplace(path, old, new, backup_path=None, encoding="auto"):
    """Thay thế chuỗi nhị phân trong AXML/ARSC in-place.

    Hỗ trợ auto-detect cả chuỗi UTF-8 và UTF-16LE, tự đệm null bytes và sao lưu an toàn.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError("Không tìm thấy tệp: %s" % path)

    if not old:
        raise ValueError("old không được để trống")

    with open(path, "rb") as fh:
        raw = fh.read()

    # Xác định byte representation cho old và new
    matched_enc = None
    old_b = None
    new_b = None

    if isinstance(old, (bytes, bytearray)):
        old_b = bytes(old)
        new_b = bytes(new) if isinstance(new, (bytes, bytearray)) else str(new).encode("utf-8")
        matched_enc = "raw"
    else:
        # Dạng chuỗi string -> kiểm tra encoding
        if encoding in ("auto", "utf-8") and old.encode("utf-8") in raw:
            matched_enc = "utf-8"
            old_b = old.encode("utf-8")
            new_b = new.encode("utf-8")
        elif encoding in ("auto", "utf-16le") and old.encode("utf-16le") in raw:
            matched_enc = "utf-16le"
            old_b = old.encode("utf-16le")
            new_b = new.encode("utf-16le")
        else:
            # Fallback mặc định theo encoding được chỉ định
            matched_enc = encoding if encoding != "auto" else "utf-8"
            old_b = old.encode("utf-8")
            new_b = new.encode("utf-8")

    if len(new_b) > len(old_b):
        raise ValueError(
            "new (%d bytes) dài hơn old (%d bytes); không thể patch in-place"
            % (len(new_b), len(old_b))
        )

    hits = raw.count(old_b)
    if backup_path and hits > 0:
        bdir = os.path.dirname(os.path.abspath(backup_path))
        if bdir:
            os.makedirs(bdir, exist_ok=True)
        shutil.copy2(path, backup_path)

    if hits > 0:
        padding_len = len(old_b) - len(new_b)
        padded_new = new_b + b"\x00" * padding_len
        raw = raw.replace(old_b, padded_new)
        with open(path, "wb") as fh:
            fh.write(raw)

    return {
        "path": path,
        "hits": hits,
        "encoding": matched_enc,
        "size": len(raw),
        "backup": backup_path if hits > 0 else None,
    }
