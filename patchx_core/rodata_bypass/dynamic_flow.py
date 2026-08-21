# -*- coding: utf-8 -*-
"""rodata_bypass.dynamic_flow — LUỒNG BYPASS ĐỘNG.

Toàn bộ luồng patch chuỗi .rodata TRÊN RAM bằng Frida khi app đang chạy
(không sửa file .so/.elf gốc, không giới hạn độ dài chuỗi mới):
  find (tìm RVA) -> sinh script Frida (inline/pointer/both/runtime-scan)
  -> hướng dẫn chạy frida / gadget / remote-observe.

Chiến lược:
  - inline : ghi đè trực tiếp (script tự kiểm tra dung lượng; bỏ qua nếu
    vượt trừ allow_overflow).
  - pointer: đổi con trỏ tới chuỗi mới cấp phát (an toàn, độ dài vô hạn).
  - runtime-scan: quét RAM module tìm chuỗi cũ rồi ghi inline (không cần RVA).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..behavior.rodata_patcher import (
    ElfReader,
    find_string_offsets,
    generate_rodata_patch_script,
    normalize_rodata_patches,
    write_rodata_script,
)


def _coerce_int(value, name):
    """Ép số từ int/str (vd '0x1A2B3') — trả None nếu value None."""
    if value is None or isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError:
        raise ValueError("%s không hợp lệ: %r" % (name, value))


DEFAULT_OUT = Path("outputs") / "behavior" / "rodata_patch.js"


class DynamicBypassFlow:
    """Bypass động: tìm RVA chuỗi + sinh script Frida patch RAM."""

    def __init__(self, so_path: str | Path):
        self.so_path = Path(so_path)
        self.reader = ElfReader(self.so_path)

    def sections(self) -> List[Dict[str, Any]]:
        return self.reader.list_alloc_sections()

    def find(self, needle: str, all_hits: bool = False) -> List[Any]:
        return find_string_offsets(self.so_path, needle, all_hits=all_hits)

    def generate(self, patches: List[Dict[str, Any]],
                 out_path: Optional[str | Path] = None,
                 restore: bool = True,
                 allow_overflow: bool = False) -> Path:
        """Sinh script Frida và ghi file — trả đường dẫn script."""
        target = Path(out_path or DEFAULT_OUT)
        write_rodata_script(
            patches, target,
            restore=restore,
            allow_overflow=allow_overflow,
            so_path=self.so_path)
        return target

    def script_text(self, patches: List[Dict[str, Any]],
                    restore: bool = True,
                    allow_overflow: bool = False) -> str:
        """Sinh nội dung script Frida (không ghi file)."""
        return generate_rodata_patch_script(
            patches, restore=restore, allow_overflow=allow_overflow,
            so_path=self.so_path)

    def run(self, needle: Optional[str] = None,
            new_string: Optional[str] = None,
            offset: Optional[int] = None,
            ptr_offset: Optional[int] = None,
            mode: str = "both",
            runtime_scan: bool = False,
            out_path: Optional[str | Path] = None,
            restore: bool = True,
            allow_overflow: bool = False) -> Path:
        """Luồng động đầy đủ: tìm RVA (nếu cần) -> sinh script Frida.

        Trả đường dẫn script đã ghi; ValueError khi thiếu tham số hoặc
        không xác định được vị trí.
        """
        if new_string is None:
            raise ValueError("Luồng động cần new_string (chuỗi mới)")
        patch: Dict[str, Any] = {
            "new_string": new_string,
            "mode": mode,
            "runtime_scan": bool(runtime_scan),
        }
        if offset is not None:
            patch["rva"] = _coerce_int(offset, "offset")
        if ptr_offset is not None:
            patch["ptr_rva"] = _coerce_int(ptr_offset, "ptr_offset")
        if needle is not None:
            patch["old_string"] = needle
        normalize_rodata_patches([patch], so_path=self.so_path)
        return self.generate([patch], out_path=out_path,
                             restore=restore,
                             allow_overflow=allow_overflow)
