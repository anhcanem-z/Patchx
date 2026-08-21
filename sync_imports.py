#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PatchX - Đồng bộ import nội bộ dựa trên cấu trúc file.

Mặc định:
    python3 sync_imports.py .

Chỉ kiểm tra:
    python3 sync_imports.py .

Tự động thêm import còn thiếu:
    python3 sync_imports.py . --apply

Tạo backup trước khi sửa:
    python3 sync_imports.py . --apply --backup
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
from pathlib import Path


PY_EXT = ".py"

# Không đụng vào các thư mục này
SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
}

# Các tên thường không cần tự import
BUILTINS = set(dir(__builtins__))


# ============================================================
# PACKAGE DISCOVERY
# ============================================================

def find_package_root(root: Path) -> Path:
    """
    Tìm thư mục chứa package patchx_core.
    """
    if (root / "patchx_core").is_dir():
        return root / "patchx_core"

    if root.name == "patchx_core":
        return root

    for p in root.rglob("patchx_core"):
        if p.is_dir():
            return p

    raise SystemExit(
        "[ERROR] Không tìm thấy thư mục patchx_core trong: "
        + str(root)
    )


def python_files(package_root: Path):
    for path in package_root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def module_name(package_root: Path, path: Path) -> str:
    """
    Ví dụ:

        patchx_core/behavior/detector.py

    thành:

        patchx_core.behavior.detector
    """
    rel = path.relative_to(package_root.parent)

    parts = list(rel.parts)

    if parts[-1] == "__init__.py":
        parts.pop()

    else:
        parts[-1] = parts[-1][:-3]

    return ".".join(parts)


# ============================================================
# MODULE INDEX
# ============================================================

def build_module_index(package_root: Path):
    """
    Tạo:

        module -> file

    và:

        exported symbol -> module
    """

    modules = {}
    symbols = {}

    for path in python_files(package_root):
        mod = module_name(package_root, path)
        modules[mod] = path

        try:
            tree = ast.parse(
                path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            )
        except SyntaxError:
            continue

        for node in tree.body:

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.setdefault(node.name, []).append(mod)

            elif isinstance(node, ast.ClassDef):
                symbols.setdefault(node.name, []).append(mod)

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols.setdefault(
                            target.id,
                            [],
                        ).append(mod)

    return modules, symbols


# ============================================================
# IMPORT ANALYSIS
# ============================================================

def existing_imports(tree):
    """
    Lấy các symbol/module đã import.
    """

    imported_names = set()
    imported_modules = set()

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):

            for alias in node.names:
                imported_modules.add(alias.name)

                imported_names.add(
                    alias.asname or alias.name.split(".")[0]
                )

        elif isinstance(node, ast.ImportFrom):

            if node.module:
                imported_modules.add(node.module)

            for alias in node.names:

                if alias.name == "*":
                    continue

                imported_names.add(
                    alias.asname or alias.name
                )

    return imported_names, imported_modules


# ============================================================
# USED SYMBOLS
# ============================================================

class NameCollector(ast.NodeVisitor):

    def __init__(self):
        self.used = set()
        self.defined = set()

    def visit_Name(self, node):
        self.used.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.defined.add(node.name)

        for arg in node.args.args:
            self.defined.add(arg.arg)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.defined.add(node.name)

        for arg in node.args.args:
            self.defined.add(arg.arg)

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.defined.add(node.name)
        self.generic_visit(node)


def find_missing_symbols(tree, imported_names):
    collector = NameCollector()
    collector.visit(tree)

    missing = (
        collector.used
        - collector.defined
        - imported_names
        - BUILTINS
    )

    return missing


# ============================================================
# RELATIVE IMPORT
# ============================================================

def relative_import(current_module, target_module):
    """
    Tạo import tương đối.

    Ví dụ:

        current:
            patchx_core.cli

        target:
            patchx_core.behavior.detector

        =>

            from .behavior.detector import X
    """

    current_parts = current_module.split(".")
    target_parts = target_module.split(".")

    # module cuối của current không phải package
    current_pkg = current_parts[:-1]

    common = 0

    for a, b in zip(current_pkg, target_parts):
        if a != b:
            break
        common += 1

    up = len(current_pkg) - common

    if up == 0:
        dots = "."
    else:
        dots = "." * (up + 1)

    remainder = target_parts[common:]

    if not remainder:
        return dots.rstrip(".")

    return dots + ".".join(remainder)


# ============================================================
# FIND CANDIDATE IMPORTS
# ============================================================

def find_candidates(
    current_module,
    missing,
    symbol_index,
):
    candidates = []

    for name in sorted(missing):

        locations = symbol_index.get(name, [])

        # Chỉ nhận symbol có đúng một nơi định nghĩa
        # để tránh import nhầm.
        if len(locations) != 1:
            continue

        target = locations[0]

        # Không import chính module hiện tại
        if target == current_module:
            continue

        prefix = relative_import(
            current_module,
            target,
        )

        candidates.append(
            (
                name,
                target,
                f"from {prefix} import {name}",
            )
        )

    return candidates


# ============================================================
# CHECK ONE FILE
# ============================================================

def analyze_file(
    package_root,
    path,
    symbol_index,
):
    try:
        source = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

        tree = ast.parse(source)

    except SyntaxError as exc:

        return {
            "status": "SYNTAX_ERROR",
            "path": path,
            "error": str(exc),
            "candidates": [],
        }

    current = module_name(
        package_root,
        path,
    )

    imported_names, _ = existing_imports(tree)

    missing = find_missing_symbols(
        tree,
        imported_names,
    )

    candidates = find_candidates(
        current,
        missing,
        symbol_index,
    )

    return {
        "status": "OK",
        "path": path,
        "module": current,
        "missing": missing,
        "candidates": candidates,
    }


# ============================================================
# APPLY
# ============================================================

def add_imports(
    path: Path,
    imports,
    backup=False,
):
    if not imports:
        return False

    source = path.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    if backup:
        shutil.copy2(
            path,
            path.with_suffix(path.suffix + ".bak"),
        )

    lines = source.splitlines(keepends=True)

    # Tìm vị trí cuối import block
    insert_at = 0

    shebang = False

    if lines and lines[0].startswith("#!"):
        insert_at = 1
        shebang = True

    # encoding / module header
    while insert_at < len(lines):
        line = lines[insert_at].strip()

        if (
            line.startswith("#")
            or not line
        ):
            insert_at += 1
            continue

        break

    # Nếu có module docstring thì giữ nguyên docstring
    try:
        tree = ast.parse(source)

        if (
            tree.body
            and isinstance(
                tree.body[0],
                ast.Expr,
            )
            and isinstance(
                tree.body[0].value,
                ast.Constant,
            )
            and isinstance(
                tree.body[0].value.value,
                str,
            )
        ):
            end_line = tree.body[0].end_lineno
            insert_at = max(
                insert_at,
                end_line,
            )

    except SyntaxError:
        return False

    new_imports = []

    for imp in imports:

        # Chống duplicate
        if re.search(
            r"^\s*" + re.escape(imp) + r"\s*$",
            source,
            re.MULTILINE,
        ):
            continue

        new_imports.append(
            imp + "\n"
        )

    if not new_imports:
        return False

    lines[insert_at:insert_at] = (
        new_imports + ["\n"]
    )

    path.write_text(
        "".join(lines),
        encoding="utf-8",
        newline="\n",
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "PatchX - đồng bộ import nội bộ "
            "dựa trên cấu trúc package."
        )
    )

    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Thư mục _patchx hoặc thư mục chứa patchx_core",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Tự động thêm import còn thiếu",
    )

    parser.add_argument(
        "--backup",
        action="store_true",
        help="Tạo .bak trước khi sửa",
    )

    args = parser.parse_args()

    root = Path(args.root).resolve()

    package_root = find_package_root(root)

    print(
        "[patchx-import] Package:",
        package_root,
    )

    modules, symbol_index = build_module_index(
        package_root
    )

    print(
        "[patchx-import] Phát hiện %d module Python"
        % len(modules)
    )

    changed = 0
    warnings = 0

    for path in sorted(
        python_files(package_root)
    ):

        result = analyze_file(
            package_root,
            path,
            symbol_index,
        )

        rel = path.relative_to(root)

        if result["status"] == "SYNTAX_ERROR":

            print(
                "[SYNTAX] %s: %s"
                % (
                    rel,
                    result["error"],
                )
            )

            warnings += 1
            continue

        candidates = result["candidates"]

        if not candidates:
            print(
                "[OK]     %s"
                % rel
            )
            continue

        print(
            "[IMPORT] %s"
            % rel
        )

        imports = []

        for name, target, statement in candidates:

            print(
                "         + %s"
                % statement
            )

            imports.append(statement)

        if args.apply:

            if add_imports(
                path,
                imports,
                backup=args.backup,
            ):
                print(
                    "         -> ĐÃ THÊM"
                )
                changed += 1

    print()
    print(
        "========================================"
    )
    print(
        "Module      : %d"
        % len(modules)
    )
    print(
        "Đã sửa      : %d"
        % changed
    )
    print(
        "Cảnh báo    : %d"
        % warnings
    )
    print(
        "========================================"
    )

    if not args.apply:
        print(
            "Chưa thay đổi file."
        )
        print(
            "Muốn áp dụng:"
        )
        print(
            "  python3 sync_imports.py . --apply"
        )


if __name__ == "__main__":
    main()
