from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List


class SmaliPatcher:
    """Tu dong doc Target va ap dung patch vao cac file .smali."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.patched_files: List[str] = []

    def apply_targets(self, targets: List[Any]) -> dict[str, Any]:
        results = {"success": 0, "failed": 0, "details": []}

        for target in targets:
            target_dict = target.to_dict() if hasattr(target, "to_dict") else target
            strategy = target_dict.get("suggested_actions", {}).get("auto_strategy", {})
            source = target_dict.get("source")

            if not strategy or not source or not Path(source).exists():
                continue

            patch_mode = strategy.get("patch_mode")
            success = False

            if patch_mode == "force_boolean_true":
                success = self._patch_boolean_method(source, strategy.get("target_method"), return_value=True)
            elif patch_mode == "billing_response_ok":
                success = self._patch_billing_ok(source, strategy.get("target_method"))
            elif patch_mode == "nop_method_or_hook":
                success = self._patch_nop_method(source, strategy.get("target_method"))
            elif patch_mode == "force_login_success":
                success = self._patch_login_success(source, strategy.get("target_method"))
            elif patch_mode == "fake_logged_in":
                success = self._patch_fake_logged_in(source, strategy.get("target_method"))
            elif patch_mode == "skip_login_gate":
                success = self._patch_skip_login_gate(source, strategy.get("target_method"))

            if success:
                results["success"] += 1
                if source not in self.patched_files:
                    self.patched_files.append(source)
                results["details"].append({"file": source, "status": "patched", "mode": patch_mode})
            else:
                results["failed"] += 1

        return results

    def _patch_boolean_method(self, file_path: str, method_name: str, return_value: bool = True) -> bool:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        val_hex = "0x1" if return_value else "0x0"

        if not method_name:
            return False

        pattern = re.compile(
            rf"(\.method[^\n]*\b{re.escape(method_name)}\b[^\n]*\n)(.*?)(\.end\s+method)",
            re.DOTALL,
        )

        def replace_body(match):
            head = match.group(1)
            end = match.group(3)
            new_body = f"    .registers 1\n    const/4 v0, {val_hex}\n    return v0\n"
            return f"{head}{new_body}{end}"

        new_content, count = pattern.subn(replace_body, content)
        if count > 0:
            path.write_text(new_content, encoding="utf-8")
            return True
        return False

    def _patch_billing_ok(self, file_path: str, method_name: str) -> bool:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")

        if "getResponseCode" in content or "onPurchasesUpdated" in content:
            # Chen return 0 (OK) cho Response Code
            pattern = re.compile(r"(\.method[^\n]*getResponseCode[^\n]*\n)(.*?)(\.end\s+method)", re.DOTALL)
            new_content, count = pattern.subn(
                r"\1    .registers 1\n    const/4 v0, 0x0\n    return v0\n\3", content
            )
            if count > 0:
                path.write_text(new_content, encoding="utf-8")
                return True
        return False

    def _patch_nop_method(self, file_path: str, method_name: str) -> bool:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")

        if not method_name:
            method_name = "checkServerTrusted"

        pattern = re.compile(
            rf"(\.method[^\n]*\b{re.escape(method_name)}\b[^\n]*\n)(.*?)(\.end\s+method)",
            re.DOTALL,
        )
        new_content, count = pattern.subn(
            r"\1    .registers 0\n    return-void\n\3", content
        )
        if count > 0:
            path.write_text(new_content, encoding="utf-8")
            return True
        return False

    # =====================================================
    # LOGIN BYPASS / FAKE LOGGED-IN
    # =====================================================

    @staticmethod
    def _method_return_type(content: str, method_name: str) -> str:
        pattern = re.compile(
            rf"(?m)^\.method[^\n]*\b{re.escape(method_name)}\b[^\n]*\n"
        )
        match = pattern.search(content)
        if not match:
            return ""
        return_match = re.search(r"\)\s*([^\s]+)", match.group(0))
        return return_match.group(1) if return_match else ""

    @staticmethod
    def _smali_parameter_register_count(method_head: str) -> int:
        match = re.search(r"\((.*?)\)", method_head)
        if not match:
            return 0

        params = match.group(1)
        index = 0
        count = 0
        while index < len(params):
            char = params[index]
            if char == "L":
                end = params.find(";", index)
                index = end + 1 if end != -1 else index + 1
                count += 1
            elif char == "[":
                index += 1
                if index < len(params) and params[index] == "L":
                    end = params.find(";", index)
                    index = end + 1 if end != -1 else index + 1
                count += 1
            elif char in {"J", "D"}:
                index += 1
                count += 2
            else:
                index += 1
                count += 1
        return count

    def _rewrite_method_return(
        self,
        path: Path,
        content: str,
        method_name: str,
        instructions: str,
    ) -> bool:
        pattern = re.compile(
            rf"(\.method[^\n]*\b{re.escape(method_name)}\b[^\n]*\n)(.*?)(\.end\s+method)",
            re.DOTALL,
        )

        def replace_body(match):
            head = match.group(1)
            end = match.group(3)
            param_count = self._smali_parameter_register_count(head)
            is_static = " static " in head.lower()
            register_count = param_count + (0 if is_static else 1) + 1
            return (
                f"{head}"
                f"    .registers {register_count}\n"
                f"{instructions}"
                f"{end}"
            )

        new_content, count = pattern.subn(replace_body, content)
        if count > 0:
            path.write_text(new_content, encoding="utf-8")
            return True
        return False

    def _patch_login_success(self, file_path: str, method_name: str) -> bool:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        if not method_name:
            return False

        return_type = self._method_return_type(content, method_name)
        if return_type == "V":
            return False
        if return_type.startswith("L"):
            return False

        instructions = "    const/4 v0, 0x1\n    return v0\n"
        return self._rewrite_method_return(
            path,
            content,
            method_name,
            instructions,
        )

    def _patch_fake_logged_in(self, file_path: str, method_name: str) -> bool:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        if not method_name:
            return False

        return_type = self._method_return_type(content, method_name)
        if return_type == "V" or return_type.startswith("L"):
            return False

        instructions = "    const/4 v0, 0x1\n    return v0\n"
        return self._rewrite_method_return(
            path,
            content,
            method_name,
            instructions,
        )

    def _patch_skip_login_gate(self, file_path: str, method_name: str) -> bool:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        if not method_name:
            return False

        return_type = self._method_return_type(content, method_name)
        if return_type == "V":
            instructions = "    return-void\n"
        elif return_type.startswith("L"):
            return False
        else:
            instructions = "    const/4 v0, 0x1\n    return v0\n"

        return self._rewrite_method_return(
            path,
            content,
            method_name,
            instructions,
        )
