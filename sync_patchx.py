#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PatchX module synchronizer / orchestrator.

Mục tiêu:
- Quét patchx_core theo cấu trúc package thực tế.
- Kiểm tra import nội bộ bằng AST.
- Compile toàn bộ package.
- Tự tạo import cho các module PatchX đã biết trong cli.py/behavior.
- Không xóa import cũ.
- Không gọi các thao tác patch/inject; chỉ đồng bộ và smoke-test module.

Usage:
    python3 sync_patchx.py .
    python3 sync_patchx.py . --apply
    python3 sync_patchx.py . --smoke
    python3 sync_patchx.py . --apply --smoke
"""

from __future__ import annotations

import argparse
import ast
import compileall
import shutil
from pathlib import Path


CORE = Path("patchx_core")

# Module/symbol chính của pipeline hiện tại.
IMPORT_PLAN = {
    "patchx_core/cli.py": [
        ("from .behavior.detector import BehaviorDetector", "BehaviorDetector"),
        ("from .behavior.target import TargetAnalyzer", "TargetAnalyzer"),
        ("from .behavior.frida_generator import FridaScriptGenerator", "FridaScriptGenerator"),
    ],
    "patchx_core/behavior/detector.py": [
        ("from .cfg import build_cfg, CFGBuilder", "build_cfg"),
        ("from .cfg import build_cfg, CFGBuilder", "CFGBuilder"),
        ("from .model import Behavior, Evidence", "Behavior"),
        ("from .model import Behavior, Evidence", "Evidence"),
        ("from .ontology import BEHAVIORS", "BEHAVIORS"),
    ],
    "patchx_core/behavior/frida_generator.py": [
        ("from .crypto_interceptor import CryptoInterceptorGenerator",
         "CryptoInterceptorGenerator"),
    ],
}

# Chỉ smoke-test import; không thực thi patch/injection.
SMOKE_MODULES = [
    "patchx_core.behavior.cfg",
    "patchx_core.behavior.model",
    "patchx_core.behavior.ontology",
    "patchx_core.behavior.detector",
    "patchx_core.behavior.target",
    "patchx_core.behavior.frida_generator",
    "patchx_core.behavior.patcher",
    "patchx_core.behavior.crypto_interceptor",
    "patchx_core.behavior.rodata_patcher",
    "patchx_core.behavior.smart_scanner",
    "patchx_core.behavior.smart_ontology",
    "patchx_core.rodata_bypass.static_flow",
    "patchx_core.rodata_bypass.dynamic_flow",
    "patchx_core.rodata_bypass.main",
    "patchx_core.feature_menu",
    "patchx_core.cli",
]


def existing_import_names(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    names = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])

        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    names.add(a.asname or a.name)

    return names


def add_imports(path: Path, entries: list[tuple[str, str]]) -> bool:
    if not path.exists():
        print(f"[SKIP] {path}: không tồn tại")
        return False

    source = path.read_text(encoding="utf-8", errors="ignore")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"[SYNTAX] {path}: {exc}")
        return False

    names = existing_import_names(source)
    missing = []

    for statement, symbol in entries:
        if symbol not in names and statement not in source:
            missing.append(statement)

    if not missing:
        print(f"[OK]     {path}")
        return False

    print(f"[IMPORT] {path}")
    for item in missing:
        print(f"         + {item}")

    if not APPLY:
        return False

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)

    lines = source.splitlines(keepends=True)

    # Giữ shebang, encoding comment và module docstring.
    insert_at = 0

    if lines and lines[0].startswith("#!"):
        insert_at = 1

    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if not stripped or stripped.startswith("#"):
            insert_at += 1
        else:
            break

    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        insert_at = max(insert_at, tree.body[0].end_lineno)

    block = [x + "\n" for x in missing]
    lines[insert_at:insert_at] = block + ["\n"]

    path.write_text("".join(lines), encoding="utf-8")
    print(f"         -> ĐÃ THÊM; backup: {backup.name}")
    return True


def check_structure(root: Path) -> bool:
    core = root / CORE
    if not core.is_dir():
        print(f"[ERROR] Không tìm thấy {core}")
        return False

    print(f"[CORE]   {core.resolve()}")

    for rel in IMPORT_PLAN:
        p = root / rel
        if p.exists():
            print(f"[FOUND]  {rel}")
        else:
            print(f"[MISS]   {rel}")

    return True


def compile_core(root: Path) -> bool:
    print("\n[COMPILE] patchx_core")
    ok = compileall.compile_dir(
        str(root / CORE),
        quiet=1,
        force=True,
    )
    print("[COMPILE] OK" if ok else "[COMPILE] FAILED")
    return ok


def smoke_imports(root: Path) -> bool:
    import importlib
    import sys

    print("\n[SMOKE] Import module")
    sys.path.insert(0, str(root))

    all_ok = True

    for name in SMOKE_MODULES:
        try:
            importlib.import_module(name)
            print(f"[OK]     {name}")
        except Exception as exc:
            all_ok = False
            print(f"[FAIL]   {name}: {type(exc).__name__}: {exc}")

    return all_ok


def main():
    global APPLY

    parser = argparse.ArgumentParser(
        description="Đồng bộ import và kiểm tra module PatchX."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="thư mục _patchx",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="thêm import còn thiếu",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="import thử các module chính",
    )

    args = parser.parse_args()
    APPLY = args.apply

    root = Path(args.root).resolve()

    print("========================================")
    print(" PatchX Import / Module Sync")
    print("========================================")

    if not check_structure(root):
        raise SystemExit(1)

    changed = 0

    print("\n[SYNC] Import plan")
    for rel, entries in IMPORT_PLAN.items():
        if add_imports(root / rel, entries):
            changed += 1

    print(f"\n[SYNC] File thay đổi: {changed}")

    compile_ok = compile_core(root)

    smoke_ok = True
    if args.smoke:
        smoke_ok = smoke_imports(root)

    print("\n========================================")
    print(f"Compile : {'OK' if compile_ok else 'FAILED'}")
    print(f"Smoke   : {'OK' if smoke_ok else 'FAILED'}")
    print(f"Apply   : {'YES' if args.apply else 'NO'}")
    print("========================================")

    if not compile_ok or not smoke_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    APPLY = False
    main()
