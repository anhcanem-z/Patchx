# -*- coding: utf-8 -*-
"""PatchX rodata-bypass — bộ bypass riêng (tách biệt khỏi CLI cũ).

Hai thành phần:
  - LUỒNG TĨNH (StaticBypassFlow): tìm RVA chuỗi + ghi đè TRỰC TIẾP vào file
    .so (patch file, không cần Frida) — giới hạn độ dài chuỗi mới.
  - LUỒNG ĐỘNG (DynamicBypassFlow): tìm RVA chuỗi + sinh script Frida patch
    trên RAM khi app chạy — chuỗi mới độ dài vô hạn (inline/pointer/runtime).

Main hiển thị riêng: `python3 -m patchx_core.rodata_bypass` hoặc
`python3 rodata_bypass_main.py`.
"""

from .static_flow import StaticBypassFlow
from .dynamic_flow import DynamicBypassFlow
from .main import main, BANNER

__all__ = [
    "StaticBypassFlow",
    "DynamicBypassFlow",
    "main",
    "BANNER",
]
