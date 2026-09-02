# -*- coding: utf-8 -*-
"""Bộ thao tác nhị phân an toàn cho AXML và ARSC (Kế thừa và tối ưu từ Modder Hub).

Hỗ trợ:
- Phân tích cấu trúc Chunk (RES_XML_TYPE, RES_STRING_POOL_TYPE, RES_XML_RESOURCE_MAP_TYPE, ...).
- Tự động nhận diện chuỗi String Pool ở cả 2 chuẩn mã hóa UTF-8 và UTF-16LE.
- Thay thế chuỗi nhị phân in-place an toàn với padding null bytes và tạo backup.
- Trích xuất danh sách chuỗi và báo cáo bảo mật Manifest (permissions, flags, networkSecurityConfig).
- Bypass Network Security Config (chống SSL Pinning tầng XML) và can thiệp permissions in-place.
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
        "strings_start": strings_start,
        "styles_start": styles_start,
        "encoding": "utf-8" if is_utf8 else "utf-16le",
    }


def parse_strings(data):
    """Trích xuất toàn bộ chuỗi text từ String Pool của AXML/ARSC."""
    sp = inspect_string_pool(data)
    if not sp:
        return []

    off = sp["offset"]
    str_count = sp["string_count"]
    strings_start = sp["strings_start"]
    is_utf8 = sp["is_utf8"]

    if off + 28 + str_count * 4 > len(data):
        return []

    offsets = [struct.unpack_from("<I", data, off + 28 + i * 4)[0] for i in range(str_count)]
    pool_data_start = off + strings_start
    strings = []

    for item_off in offsets:
        cur = pool_data_start + item_off
        if cur >= len(data):
            continue
        if is_utf8:
            # UTF-8: 1-2 bytes u16 len + 1-2 bytes u8 len + utf8 bytes + \x00
            u8_len = data[cur + 1] if cur + 1 < len(data) else 0
            s_bytes = data[cur + 2 : cur + 2 + u8_len]
            decoded = s_bytes.decode("utf-8", errors="replace").split("\x00")[0]
            strings.append(decoded)
        else:
            # UTF-16LE: 2 bytes char count + utf-16le bytes + \x00\x00
            if cur + 2 > len(data):
                continue
            char_count = struct.unpack_from("<H", data, cur)[0]
            byte_len = char_count * 2
            s_bytes = data[cur + 2 : cur + 2 + byte_len]
            decoded = s_bytes.decode("utf-16le", errors="replace").split("\x00")[0]
            strings.append(decoded)

    return strings


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


def inspect_manifest_security(path):
    """Phân tích các cờ và thuộc tính bảo mật trong AndroidManifest.xml nhị phân."""
    if not os.path.isfile(path):
        raise FileNotFoundError("Không tìm thấy tệp: %s" % path)

    with open(path, "rb") as fh:
        data = fh.read()

    strings = parse_strings(data)
    perms = [s for s in strings if "permission." in s]
    has_nsc = "networkSecurityConfig" in strings
    has_cleartext = "usesCleartextTraffic" in strings
    has_debug = "debuggable" in strings

    return {
        "path": path,
        "total_strings": len(strings),
        "has_network_security_config": has_nsc,
        "has_uses_cleartext_traffic": has_cleartext,
        "has_debuggable": has_debug,
        "permissions": perms,
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

    matched_enc = None
    old_b = None
    new_b = None

    if isinstance(old, (bytes, bytearray)):
        old_b = bytes(old)
        new_b = bytes(new) if isinstance(new, (bytes, bytearray)) else str(new).encode("utf-8")
        matched_enc = "raw"
    else:
        if encoding in ("auto", "utf-8") and old.encode("utf-8") in raw:
            matched_enc = "utf-8"
            old_b = old.encode("utf-8")
            new_b = new.encode("utf-8")
        elif encoding in ("auto", "utf-16le") and old.encode("utf-16le") in raw:
            matched_enc = "utf-16le"
            old_b = old.encode("utf-16le")
            new_b = new.encode("utf-16le")
        else:
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


def bypass_network_security_config(path, backup_path=None):
    """Vô hiệu hóa Network Security Config (bỏ qua SSL Pinning do XML định nghĩa).

    Đổi tên thuộc tính networkSecurityConfig thành disabledSecConfig để Android PackageParser bỏ qua.
    """
    return replace_string_inplace(
        path,
        old="networkSecurityConfig",
        new="disabledSecConfig",
        backup_path=backup_path,
        encoding="auto",
    )


def replace_permission(path, old_permission, new_permission, backup_path=None):
    """Thay thế một permission này bằng permission khác in-place trong AXML.

    Ví dụ: đổi android.permission.ACCESS_ADSERVICES_ATTRIBUTION thành android.permission.RECORD_AUDIO
    """
    return replace_string_inplace(
        path,
        old=old_permission,
        new=new_permission,
        backup_path=backup_path,
        encoding="auto",
    )
