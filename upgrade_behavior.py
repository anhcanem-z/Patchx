from pathlib import Path
import shutil
import py_compile
import sys

ROOT = Path(__file__).resolve().parent
BEHAVIOR = ROOT / "patchx_core" / "behavior"
DETECTOR = BEHAVIOR / "detector.py"
CFG = BEHAVIOR / "cfg.py"

def backup(path):
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    print(f"[backup] {bak}")

def check(path):
    try:
        py_compile.compile(
            str(path),
            doraise=True,
        )
        print(f"[OK] {path}")
        return True
    except py_compile.PyCompileError as e:
        print(f"[FAIL] {path}")
        print(e)
        return False

def patch_detector():
    text = DETECTOR.read_text(encoding="utf-8")

    start = text.index(
        "    def _scan_smali_cfg("
    )

    end = text.index(
        "    # =====================================================\n"
        "    # CFG METHOD",
        start,
    )

    new = '''    def _scan_smali_cfg(
        self,
        path: Path,
        text: str,
        results: dict,
    ):
        """
        CFG có chọn lọc.

        Chỉ dựng CFG khi file/method chứa
        API hoặc mẫu hành vi quan tâm.
        """

        sensitive_patterns = (
            "isDebuggerConnected",
            "waitingForDebugger",
            "GET_SIGNATURES",
            "GET_SIGNING_CERTIFICATES",
            "getPackageInfo",
            "PackageManager",
            "Signature",
            "MessageDigest",
            "checkSelfPermission",
            "requestPermissions",
            "LocationManager",
            "FusedLocationProviderClient",
        )

        # -------------------------------------------------
        # Fast pre-filter cấp file
        # -------------------------------------------------

        lower_text = text.lower()

        if not any(
            p.lower() in lower_text
            for p in sensitive_patterns
        ):
            return

        # -------------------------------------------------
        # Tách method
        # -------------------------------------------------

        method_pattern = re.compile(
            r"(?ms)^\\.method[^\\n]*\\n"
            r"(.*?)"
            r"^\\.end\\s+method"
        )

        for match in method_pattern.finditer(text):

            smali_code = match.group(1)

            if not smali_code.strip():
                continue

            lower_method = smali_code.lower()

            # Chỉ CFG method có bằng chứng
            if not any(
                p.lower() in lower_method
                for p in sensitive_patterns
            ):
                continue

            method_header = (
                match.group(0)
                .split("\\n", 1)[0]
                .strip()
            )

            cfg = build_cfg(
                smali_code,
                method=method_header,
            )

            self._analyze_cfg_method(
                path,
                text,
                match,
                method_header,
                smali_code,
                cfg,
                results,
            )

'''

    DETECTOR.write_text(
        text[:start] + new + text[end:],
        encoding="utf-8",
    )

    print("[patch] detector.py: CFG selective")

def patch_permission_duplicate():
    text = DETECTOR.read_text(encoding="utf-8")

    duplicate = '''            self._scan_permission_flow(
                path,
                text,
                results,
            )

        # -------------------------------------------------
        # XML / manifest + permission
        # -------------------------------------------------

        if suffix in {
            ".xml",
            ".smali",
        }:
            self._scan_permission_flow(
                path,
                text,
                results,
            )
'''

    replacement = '''        # -------------------------------------------------
        # XML / Smali: permission
        # -------------------------------------------------

        if suffix in {
            ".xml",
            ".smali",
        }:
            self._scan_permission_flow(
                path,
                text,
                results,
            )
'''

    if duplicate in text:
        text = text.replace(
            duplicate,
            replacement,
            1,
        )
        DETECTOR.write_text(
            text,
            encoding="utf-8",
        )
        print("[patch] detector.py: removed duplicate permission scan")
    else:
        print("[info] duplicate permission block not found")

def main():
    print("[PatchX] Nâng cấp Behavior Analyzer")
    print(f"[root] {ROOT}")

    for path in (DETECTOR, CFG):
        if not path.exists():
            print(f"[ERROR] Không tìm thấy: {path}")
            return 1

    # Backup
    backup(DETECTOR)
    backup(CFG)

    # Patch
    patch_detector()
    patch_permission_duplicate()

    # Compile
    print()
    print("[check] Kiểm tra cú pháp...")

    ok = True

    for path in (CFG, DETECTOR):
        if not check(path):
            ok = False

    if not ok:
        print()
        print("[ERROR] Patch lỗi.")
        print("Có thể khôi phục:")
        print(f"  cp {DETECTOR}.bak {DETECTOR}")
        print(f"  cp {CFG}.bak {CFG}")
        return 1

    print()
    print("[OK] Behavior Analyzer đã được nâng cấp.")
    print()
    print("Chạy:")
    print("  python3 -u patchx behavior Apks/app.apk.decoded")
    print()
    print("Hoặc:")
    print("  python3 -u patchx targets Apks/app.apk.decoded")

    return 0

if __name__ == "__main__":
    sys.exit(main())
