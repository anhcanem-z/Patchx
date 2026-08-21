# -*- coding: utf-8 -*-
"""rodata_bypass.static_flow — LUỒNG BYPASS TĨNH.

Toàn bộ luồng patch chuỗi TRỰC TIẾP vào file .so/.elf (không cần Frida):
  find (tìm RVA) -> kiểm tra dung lượng -> ghi đè tại offset thật
  -> backup file gốc -> báo cáo.

Giới hạn cố hữu của patch file: chuỗi mới không được dài hơn dung lượng
chuỗi cũ (tính tới NUL), trừ khi allow_overflow=True (rủi ro tràn dữ liệu
kế bên). Muốn thay chuỗi dài hơn an toàn → dùng luồng ĐỘNG (Frida RAM).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..behavior.rodata_patcher import (
    ElfReader,
    find_string_offsets,
    normalize_rodata_patches,
    patch_so_file,
)


def _coerce_int(value, name):
    """Ép số từ int/str (vd '0x1A2B3') — trả None nếu value None."""
    if value is None or isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError:
        raise ValueError("%s không hợp lệ: %r" % (name, value))


class StaticBypassFlow:
    """Bypass tĩnh: tìm chuỗi trong .rodata/.data + ghi đè trực tiếp file .so."""

    def __init__(self, so_path: str | Path):
        self.so_path = Path(so_path)
        self.reader = ElfReader(self.so_path)

    def sections(self) -> List[Dict[str, Any]]:
        """Liệt kê section ALLOC (rodata/data...) để xem nhanh."""
        return self.reader.list_alloc_sections()

    def find(self, needle: str, all_hits: bool = False) -> List[Any]:
        """Tìm mọi vị trí chuỗi needle — trả RVA + section + offset file."""
        return find_string_offsets(self.so_path, needle, all_hits=all_hits)

    def apply(self, patches: List[Dict[str, Any]],
              out_path: Optional[str | Path] = None,
              allow_overflow: bool = False,
              backup: bool = True,
              backup_dir: Optional[str | Path] = None) -> Dict[str, Any]:
        """Ghi đè chuỗi trực tiếp vào file (mặc định có backup trước khi ghi)."""
        return patch_so_file(
            self.so_path, patches,
            out_path=out_path,
            allow_overflow=allow_overflow,
            backup=backup,
            backup_dir=backup_dir,
        )

    def run(self, needle: Optional[str] = None,
            new_string: Optional[str] = None,
            offset: Optional[int] = None,
            allow_overflow: bool = False,
            out_path: Optional[str | Path] = None,
            backup: bool = True,
            backup_dir: Optional[str | Path] = None) -> Dict[str, Any]:
        """Luồng tĩnh đầy đủ: tìm RVA (nếu cần) -> kiểm tra -> ghi file.

        Trả report của patch_so_file; ValueError khi chuỗi dài hơn dung
        lượng (trừ allow_overflow) hoặc không tìm thấy vị trí.
        """
        if new_string is None:
            raise ValueError("Luồng tĩnh cần new_string (chuỗi mới)")
        patch: Dict[str, Any] = {"new_string": new_string, "mode": "inline"}
        if offset is not None:
            patch["rva"] = _coerce_int(offset, "offset")
        if needle is not None:
            patch["old_string"] = needle
        normalize_rodata_patches([patch], so_path=self.so_path)
        return self.apply([patch], out_path=out_path,
                          allow_overflow=allow_overflow,
                          backup=backup, backup_dir=backup_dir)
