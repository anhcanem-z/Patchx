# -*- coding: utf-8 -*-
"""rodata_bypass.main — MAIN HIỂN THỊ RIÊNG cho bộ bypass rodata.

Tách biệt hoàn toàn khỏi CLI cũ (patchx rodata-* / patchx_core/cli.py).
Chạy:
    python3 -m patchx_core.rodata_bypass SO --flow static  --string X --new Y
    python3 -m patchx_core.rodata_bypass SO --flow dynamic --string X --new Y --mode pointer
    python3 rodata_bypass_main.py SO --flow static --string X --new Y
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .static_flow import StaticBypassFlow
from .dynamic_flow import DynamicBypassFlow

BANNER = """\
=====================================================================
  PatchX rodata-bypass — BỘ BYPASS RIÊNG (tách khỏi CLI cũ)
---------------------------------------------------------------------
  [1] LUỒNG TĨNH   (--flow static)  : patch TRỰC TIẾP vào file .so
      find RVA -> ghi đè tại offset thật -> backup -> không cần Frida
      (giới hạn: chuỗi mới không dài hơn chuỗi cũ, trừ --allow-overflow)
  [2] LUỒNG ĐỘNG   (--flow dynamic) : patch TRÊN RAM bằng Frida khi app
      chạy -> sinh script, chuỗi mới độ dài vô hạn (inline/pointer/runtime)
====================================================================="""

OUT_DEFAULT_STATIC = "outputs/behavior/rodata_test/apply"
OUT_DEFAULT_DYNAMIC = "outputs/behavior/rodata_patch.js"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rodata_bypass",
        description="PatchX rodata-bypass — luồng tĩnh (patch file) + luồng "
                    "động (Frida RAM), main hiển thị riêng.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ví dụ:\n"
               "  python3 -m patchx_core.rodata_bypass lib.so --flow static \\\n"
               "      --string 'https://old.example.com/v1' --new 'https://new.example.com/x'\n"
               "  python3 -m patchx_core.rodata_bypass lib.so --flow dynamic \\\n"
               "      --string 'https://old.example.com/v1' --new 'https://new.example.com/long-path' \\\n"
               "      --mode pointer --ptr-offset 0x2c000")
    p.add_argument("so", help="File .so/.elf mục tiêu")
    p.add_argument("--flow", choices=["static", "dynamic"], required=True,
                   help="static = patch trực tiếp file .so; dynamic = sinh script Frida RAM")
    p.add_argument("--string", default=None,
                   help="Chuỗi gốc cần thay (tự tìm RVA; nhiều vị trí thì dùng --offset)")
    p.add_argument("--new", dest="new_string", default=None,
                   help="Chuỗi mới (dynamic: độ dài tùy ý; static: không dài hơn chuỗi cũ)")
    p.add_argument("--offset", default=None, help="RVA chuỗi gốc (vd 0x1A2B3)")
    p.add_argument("--ptr-offset", dest="ptr_offset", default=None,
                   help="RVA ô nhớ giữ con trỏ tới chuỗi cũ (dynamic, mode pointer)")
    p.add_argument("--mode", choices=["inline", "pointer", "both"], default="both",
                   help="dynamic: inline/pointer/both (mặc định both)")
    p.add_argument("--runtime-scan", dest="runtime_scan", action="store_true",
                   help="dynamic: quét RAM module tìm chuỗi cũ rồi ghi inline (không cần RVA)")
    p.add_argument("--allow-overflow", dest="allow_overflow", action="store_true",
                   help="Cho phép ghi dài hơn dung lượng chuỗi cũ (rủi ro tràn)")
    p.add_argument("--no-backup", dest="no_backup", action="store_true",
                   help="static: không tạo bản backup")
    p.add_argument("--backup-dir", dest="backup_dir", default=None,
                   help="static: thư mục backup (mặc định outputs/backup/rodata_apply/)")
    p.add_argument("--sections", action="store_true",
                   help="Liệt kê section ALLOC của file thay vì chạy luồng")
    p.add_argument("--all", dest="all_hits", action="store_true",
                   help="Tìm tất cả vị trí (kể cả ngoài vùng ánh xạ)")
    p.add_argument("--out", default=None,
                   help="File đầu ra (static: file .so mới; dynamic: script .js)")
    return p


def _print_sections(flow) -> None:
    print("[rodata-bypass] Section ALLOC trong %s:" % flow.so_path)
    for s in flow.sections():
        print("  %-20s addr=0x%x | file=0x%x | size=0x%x"
              % (s["name"], s["addr"], s["offset"], s["size"]))


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    print(BANNER)
    print()

    try:
        if args.flow == "static":
            flow = StaticBypassFlow(args.so)
            if args.sections:
                _print_sections(flow)
                return 0
            if not args.new_string:
                print("[rodata-bypass] Lỗi: luồng tĩnh cần --new (chuỗi mới)")
                return 2
            if args.runtime_scan or args.ptr_offset or args.mode != "both":
                print("[rodata-bypass] Cảnh báo: luồng tĩnh chỉ hỗ trợ inline; "
                      "bỏ qua --mode/--ptr-offset/--runtime-scan")
            report = flow.run(
                needle=args.string,
                new_string=args.new_string,
                offset=args.offset,
                allow_overflow=args.allow_overflow,
                backup=not args.no_backup,
                backup_dir=args.backup_dir,
                out_path=args.out,
            )
            print("[rodata-bypass] === LUỒNG TĨNH — ĐÃ PATCH FILE ===")
            print("[rodata-bypass] File: %s" % report["out"])
            if report.get("backup"):
                print("[rodata-bypass] Backup: %s" % report["backup"])
            for p in report["patched"]:
                print("  rva=0x%x | offset=0x%x | %s | %r -> %r%s" % (
                    p["rva"], p["file_offset"], p["section"],
                    p["old_value"], p["new_value"],
                    " (TRÀN)" if p["overflow"] else ""))
            return 0

        flow = DynamicBypassFlow(args.so)
        if args.sections:
            _print_sections(flow)
            return 0
        if not args.new_string:
            print("[rodata-bypass] Lỗi: luồng động cần --new (chuỗi mới)")
            return 2
        out = flow.run(
            needle=args.string,
            new_string=args.new_string,
            offset=args.offset,
            ptr_offset=args.ptr_offset,
            mode=args.mode,
            runtime_scan=args.runtime_scan,
            allow_overflow=args.allow_overflow,
            out_path=args.out,
        )
        print("[rodata-bypass] === LUỒNG ĐỘNG — ĐÃ SINH SCRIPT FRIDA ===")
        print("[rodata-bypass] Script: %s" % out)
        print("[rodata-bypass] Chạy: frida -U -f <package> -l %s" % out)
        print("[rodata-bypass] (hoặc nạp qua gadget-pipeline / remote-observe)")
        return 0
    except (ValueError, OSError) as exc:
        print("[rodata-bypass] Lỗi: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
