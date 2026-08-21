# -*- coding: utf-8 -*-
"""Pipeline nhung Frida Gadget vao APK khong can root.

Luong:
  app.apk / cay-apk
    -> chon/xac nhan file cau hinh
    -> thuc thi cau hinh smali
    -> thuc thi cau hinh manifest
    -> tai gadget.so
    -> nap gadget.so + script
    -> dong goi
    -> ky apk
"""

from __future__ import annotations

import json
import lzma
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .patcher import SmaliPatcher
from .smali_lib import find_method_block, first_instruction_pos


DEFAULT_GADGET_VERSION = "17.9.10"
DEFAULT_GADGET_ABI = "arm64-v8a"
DEFAULT_GADGET_URL = (
    f"https://github.com/frida/frida/releases/download/{DEFAULT_GADGET_VERSION}/"
    f"frida-gadget-{DEFAULT_GADGET_VERSION}-android-arm64.so.xz"
)

SUPPORTED_SMALI_PATCH_MODES = {
    "force_boolean_true",
    "nop_method_or_hook",
    "billing_response_ok",
    "force_login_success",
    "fake_logged_in",
    "skip_login_gate",
}

CONFIG_FILENAMES = (
    "frida_hooks_config.json",
    "frida-gadget.config.json",
    "frida-gadget.config.so",
    "libgadget.config.so",
    "loader_hook.json",
)


def _download_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "patchx-gadget"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _download_binary(url: str, dest: Path, timeout: int = 180) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "patchx-gadget"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def download_gadget(
    dest: Path,
    url: str | None = None,
    timeout: int = 180,
) -> Path:
    """Tai frida-gadget .so. URL mac dinh la ban Android arm64 tu GitHub."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    url = url or DEFAULT_GADGET_URL
    dest.parent.mkdir(parents=True, exist_ok=True)

    if url.endswith(".xz"):
        xz_path = dest.with_suffix(dest.suffix + ".xz")
        try:
            _download_binary(url, xz_path, timeout=timeout)
            with lzma.open(xz_path, "rb") as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        finally:
            if xz_path.exists():
                xz_path.unlink(missing_ok=True)
    else:
        _download_binary(url, dest, timeout=timeout)

    os.chmod(dest, 0o755)
    return dest


def find_config_candidates(search_dirs: Iterable[Path]) -> List[Path]:
    """Tim cac file cau hinh Frida/Gadget pho bien gan nhat."""
    seen: set[str] = set()
    out: List[Path] = []
    for root in search_dirs:
        root = Path(root)
        if not root.exists():
            continue
        for name in CONFIG_FILENAMES:
            try:
                for path in root.rglob(name):
                    if not path.is_file():
                        continue
                    key = str(path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(path)
            except OSError:
                continue
    return out


def _ask_yes_no(prompt: str, input_fn: Callable[[str], str]) -> bool:
    raw = input_fn(prompt).strip().lower()
    return raw in {"y", "yes", "co", "có", "1"}


def resolve_config_path(
    config_path: str | None,
    search_dirs: Iterable[Path],
    out_dir: Path,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    auto_confirm: bool = False,
) -> Path:
    """Chon config: dung tham so, hoac tu tim va xac nhan, hoac nguoi dung nhap."""
    if config_path:
        if config_path.startswith("http://") or config_path.startswith("https://"):
            remote = out_dir / "remote_config.json"
            remote.write_text(_download_text(config_path), encoding="utf-8")
            output_fn(f"[gadget] Da tai config URL -> {remote}")
            return remote
        path = Path(config_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Khong tim thay config: {path}")
        return path

    candidates = find_config_candidates(search_dirs)
    if candidates and auto_confirm:
        output_fn(f"[gadget] Tu dong chon config: {candidates[0]}")
        return candidates[0]

    if candidates:
        output_fn("[gadget] Tim thay cac file cau hinh:")
        for index, path in enumerate(candidates, 1):
            output_fn(f"  [{index}] {path}")
        raw = input_fn("Chon so, `y` de dung [1], `n` de nhap duong dan: ").strip().lower()
        if raw in {"", "y"}:
            return candidates[0]
        if raw == "n":
            pass
        elif raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(candidates):
                return candidates[index]

    raw_path = input_fn("Nhap duong dan file cau hinh (URL hoac path JSON): ").strip()
    if raw_path.startswith("http://") or raw_path.startswith("https://"):
        remote = out_dir / "remote_config.json"
        remote.write_text(_download_text(raw_path), encoding="utf-8")
        output_fn(f"[gadget] Da tai config URL -> {remote}")
        return remote
    path = Path(raw_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Khong tim thay config: {path}")
    return path


def load_hook_config(path: Path) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Tra ve (kind, hooks, raw_config).

    kind = "hooks" neu la frida_hooks_config.json; "gadget" neu la gadget config.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    data = json.loads(text)

    if isinstance(data, dict) and isinstance(data.get("hooks"), list):
        return "hooks", data["hooks"], data

    if isinstance(data, dict) and isinstance(data.get("interaction"), dict):
        return "gadget", [], data

    if isinstance(data, dict) and isinstance(data.get("targets"), list):
        return "hooks", data.get("targets", []), data

    if isinstance(data, list):
        return "hooks", data, {"hooks": data}

    return "unknown", [], data


def combine_hook_scripts(hooks: List[Dict[str, Any]], fallback: Path | None = None) -> str:
    """Ghep cac frida_script cua cac hook duoc bat thanh mot script gadget."""
    blocks: List[str] = []
    seen: set[str] = set()
    for hook in hooks:
        if hook.get("enabled") is False:
            continue
        code = hook.get("frida_script")
        if not code:
            continue
        key = code.strip()
        if key and key not in seen:
            seen.add(key)
            blocks.append(code)

    if blocks:
        return "\n\n".join(blocks)

    if fallback and fallback.exists():
        return fallback.read_text(encoding="utf-8", errors="replace")

    return "// PatchX Frida Gadget: khong co hook script.\n"


def apply_smali_config(tree: Path, hooks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Thuc thi cac hook co the patch smali tu frida_hooks_config."""
    targets: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for hook in hooks:
        if hook.get("enabled") is False:
            continue
        action = hook.get("action", {})
        target = hook.get("target", {})
        patch_mode = action.get("patch_mode")
        source = target.get("source_file") or hook.get("source")
        method = target.get("method")

        if patch_mode not in SUPPORTED_SMALI_PATCH_MODES:
            skipped.append(hook.get("id", "?"))
            continue
        if not source or not method:
            skipped.append(hook.get("id", "?"))
            continue

        targets.append(
            {
                "source": source,
                "suggested_actions": {
                    "auto_strategy": {
                        "patch_mode": patch_mode,
                        "target_method": method,
                    }
                },
            }
        )

    result: Dict[str, Any] = {"success": 0, "failed": 0, "skipped": len(skipped), "details": []}
    if targets:
        patcher = SmaliPatcher(tree)
        patch_result = patcher.apply_targets(targets)
        result.update(patch_result)
        result["skipped"] = len(skipped)
    return result


def set_extract_native_libs(tree: Path) -> bool:
    """Them android:extractNativeLibs='true' vao the <application> neu thieu."""
    manifest = Path(tree) / "AndroidManifest.xml"
    if not manifest.exists():
        return False
    text = manifest.read_text(encoding="utf-8", errors="replace")
    if "android:extractNativeLibs" in text:
        return True

    pattern = re.compile(r"(<application\b[^>]*?)(/?>)", re.S)
    new_text, count = pattern.subn(
        lambda m: m.group(1) + ' android:extractNativeLibs="true" ' + m.group(2),
        text,
        count=1,
    )
    if not count:
        return False
    manifest.write_text(new_text, encoding="utf-8")
    return True


def _normalize_gadget_resources(tree: Path) -> Dict[str, Any]:
    """Chuan hoa resource chua ky tu `$` truoc khi apktool/aapt2 build.

    Tuong duong buoc apk-fix-res: doi ten file trong res/ va cap nhat
    tham chieu trong xml/smali/text de aapt2 khong loi entry name.
    """
    res_root = Path(tree) / "res"
    changes: List[Dict[str, str]] = []
    if not res_root.is_dir():
        return {"ok": True, "changes": 0, "files": []}

    for file_path in sorted(res_root.rglob("*")):
        if not file_path.is_file() or not file_path.name.startswith("$"):
            continue

        old_name = file_path.name
        new_name = old_name.lstrip("$")
        new_path = file_path.with_name(new_name)
        if new_path.exists():
            stem, suffix = os.path.splitext(new_name)
            new_path = file_path.with_name(f"{stem}_patchx_renamed{suffix}")

        try:
            os.rename(file_path, new_path)
        except OSError:
            continue

        changes.append(
            {
                "old": old_name,
                "new": new_path.name,
                "path": str(new_path.relative_to(tree)),
            }
        )

    if not changes:
        return {"ok": True, "changes": 0, "files": []}

    pairs: List[tuple[str, str]] = []
    for change in changes:
        old_stem = os.path.splitext(change["old"])[0]
        new_stem = os.path.splitext(change["new"])[0]
        if old_stem and old_stem != new_stem:
            pairs.append((old_stem, new_stem))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)

    text_exts = (".xml", ".smali", ".txt", ".json", ".properties")
    for root, dirs, files in os.walk(tree):
        rel_parts = Path(root).relative_to(tree).parts
        if rel_parts and rel_parts[0] in {"original", ".patchx"}:
            dirs[:] = []
            continue
        for file_name in files:
            if not file_name.lower().endswith(text_exts):
                continue
            path = Path(root) / file_name
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            updated = text
            for old_stem, new_stem in pairs:
                updated = updated.replace(old_stem, new_stem)
            if updated != text:
                try:
                    path.write_text(updated, encoding="utf-8", newline="\n")
                except OSError:
                    pass

    return {"ok": True, "changes": len(changes), "files": changes}


def _manifest_package_and_classes(tree: Path) -> Tuple[str, Optional[str], Optional[str]]:
    manifest = Path(tree) / "AndroidManifest.xml"
    text = manifest.read_text(encoding="utf-8", errors="replace")
    package_match = re.search(r'\bpackage\s*=\s*["\']([^"\']+)["\']', text)
    package = package_match.group(1) if package_match else ""

    app_name: str | None = None
    app_match = re.search(r"<application\b[^>]*\bandroid:name\s*=\s*[\"']([^\"']+)[\"']", text, re.S)
    if app_match:
        app_name = app_match.group(1)

    launcher_name: str | None = None
    for block in re.finditer(r"<activity\b[^>]*>(.*?)</activity>", text, re.S):
        activity = block.group(0)
        if "android.intent.action.MAIN" not in activity or "android.intent.category.LAUNCHER" not in activity:
            continue
        name_match = re.search(r"\bandroid:name\s*=\s*[\"']([^\"']+)[\"']", activity)
        if name_match:
            launcher_name = name_match.group(1)
            break

    def expand(name: str | None) -> str | None:
        if not name:
            return None
        name = name.strip()
        if name.startswith("."):
            return (package + name) if package else name[1:]
        if "." not in name and package:
            return f"{package}.{name}"
        return name

    return package, expand(app_name), expand(launcher_name)


def _class_smali_path(tree: Path, class_name: str) -> Path:
    """Tim class smali trong tat ca smali, smali_classes2, smali_classes3..."""
    rel = class_name.replace(".", "/") + ".smali"
    for root in sorted(Path(tree).glob("smali*")):
        if not root.is_dir():
            continue
        candidate = root / rel
        if candidate.exists():
            return candidate
    return Path(tree) / "smali" / rel


def _inject_load_library(text: str, method: str) -> Tuple[str, bool]:
    """Chen System.loadLibrary('gadget') vao dau method.

    Neu method co .locals 0, nang .locals len 1 de co thanh ghi v0 an toan.
    """
    match = find_method_block(text, method)
    if not match:
        return text, False
    body = match.group(4)
    locals_match = re.search(r"(?m)^(\s*)\.locals\s+(\d+)\s*$", body)
    if not locals_match:
        return text, False

    indent = locals_match.group(1)
    locals_count = int(locals_match.group(2))
    new_text = text
    if locals_count < 1:
        abs_start = match.start(4) + locals_match.start(1)
        abs_end = match.start(4) + locals_match.end(2)
        new_text = text[:abs_start] + f"{indent}.locals 1" + text[abs_end:]
        match = find_method_block(new_text, method)
        if not match:
            return text, False

    pos = first_instruction_pos(new_text, match.start(4), match.end(4))
    block = (
        '    const-string v0, "gadget"\n\n'
        "    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V\n\n"
    )
    return new_text[:pos] + block + new_text[pos:], True


def inject_gadget_loader(tree: Path) -> Dict[str, Any]:
    """Chen lệnh load gadget vao launcher activity hoac application."""
    package, app_name, launcher_name = _manifest_package_and_classes(tree)
    candidates: List[Tuple[str, str]] = []
    if launcher_name:
        candidates.append((launcher_name, "onCreate"))
    if app_name:
        candidates.append((app_name, "attachBaseContext"))
    if launcher_name:
        candidates.append((launcher_name, "attachBaseContext"))

    for class_name, method in candidates:
        path = _class_smali_path(tree, class_name)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        new_text, ok = _inject_load_library(text, method)
        if ok:
            path.write_text(new_text, encoding="utf-8")
            return {
                "ok": True,
                "class": class_name,
                "method": method,
                "smali": str(path),
            }

    return {
        "ok": False,
        "error": "Khong tim duoc onCreate/attachBaseContext co .locals de chen loader.",
    }


def embed_gadget(
    tree: Path,
    gadget_path: Path,
    config_text: str,
    script_text: str,
    abi: str = DEFAULT_GADGET_ABI,
) -> Dict[str, Any]:
    """Nap gadget.so + config + script vao lib/<abi>/."""
    lib_dir = Path(tree) / "lib" / abi
    lib_dir.mkdir(parents=True, exist_ok=True)

    target_gadget = lib_dir / "libgadget.so"
    if gadget_path.resolve() != target_gadget.resolve():
        shutil.copy2(gadget_path, target_gadget)
    os.chmod(target_gadget, 0o755)

    config_path = lib_dir / "libgadget.config.so"
    script_path = lib_dir / "libgadget.script.so"
    config_path.write_text(config_text, encoding="utf-8")
    script_path.write_text(script_text, encoding="utf-8")

    return {
        "gadget": str(target_gadget),
        "config": str(config_path),
        "script": str(script_path),
    }


def _ensure_keystore(out_dir: Path, ks_pass: str) -> Path:
    ks = out_dir / "gadget_debug.keystore"
    if ks.exists():
        return ks
    cmd = [
        "keytool",
        "-genkeypair",
        "-v",
        "-keystore", str(ks),
        "-storepass", ks_pass,
        "-keypass", ks_pass,
        "-alias", "patchx",
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "10000",
        "-dname", "CN=PatchX, OU=PatchX, O=PatchX, L=VN, S=VN, C=VN",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip()[-500:])
    return ks


def build_and_sign(
    tree: Path,
    out_dir: Path,
    sign: bool = True,
    keystore: Path | None = None,
    ks_pass: str = "android",
) -> Dict[str, Any]:
    """Dong goi APK, zipalign va ky apksigner."""
    apktool = shutil.which("apktool")
    if not apktool:
        raise RuntimeError("Khong tim thay apktool.")
    out_dir.mkdir(parents=True, exist_ok=True)
    unsigned = out_dir / "app_unsigned.apk"
    toolkit_build = None
    try:
        from patchx_toolkit import _build_apktool as toolkit_build
    except Exception:
        toolkit_build = None

    if toolkit_build is not None:
        aapt2 = shutil.which("aapt2")
        proc, _ = toolkit_build(str(tree), str(unsigned), aapt=aapt2)
    else:
        proc = subprocess.run(
            [apktool, "b", str(tree), "-o", str(unsigned)],
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip()[-2000:])

    zipalign = shutil.which("zipalign")
    aligned = out_dir / "app_aligned.apk"
    if zipalign:
        proc = subprocess.run(
            [zipalign, "-p", "-f", "4", str(unsigned), str(aligned)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            shutil.copy2(unsigned, aligned)
    else:
        shutil.copy2(unsigned, aligned)

    if not sign:
        return {"ok": True, "apk": str(aligned), "signed": False}

    apksigner = shutil.which("apksigner")
    if not apksigner:
        return {"ok": True, "apk": str(aligned), "signed": False, "error": "Khong tim thay apksigner."}

    ks = Path(keystore).expanduser() if keystore else _ensure_keystore(out_dir, ks_pass)
    signed = out_dir / "app_signed.apk"
    cmd = [
        apksigner,
        "sign",
        "--ks", str(ks),
        "--ks-pass", f"pass:{ks_pass}",
        "--key-pass", f"pass:{ks_pass}",
        "--ks-key-alias", "patchx",
        "--out", str(signed),
        str(aligned),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {
            "ok": False,
            "apk": str(aligned),
            "signed": False,
            "error": (proc.stderr or proc.stdout or "").strip()[-2000:],
        }
    return {"ok": True, "apk": str(signed), "signed": True, "keystore": str(ks)}


def run_gadget_pipeline(
    input_path: str | Path,
    out_dir: str | Path = "outputs/behavior/gadget",
    config_path: str | None = None,
    gadget_url: str | None = None,
    gadget_path: str | Path | None = None,
    gadget_mode: str = "script",
    sign: bool = True,
    keystore: str | Path | None = None,
    ks_pass: str = "android",
    auto_confirm: bool = False,
    keep_tree: bool = False,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """Chay toan bo pipeline nhung Frida Gadget."""
    src = Path(input_path).expanduser().resolve()
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        tree = src
        decoded = False
    elif src.is_file() and src.suffix.lower() == ".apk":
        from ..diffapk import prepare_tree

        keep = str(out / "work") if keep_tree else None
        tree_str, decoded, _ = prepare_tree(str(src), keep=keep)
        tree = Path(tree_str).resolve()
    else:
        raise ValueError("input phai la thu mục cây APK hoac file .apk")

    output_fn(f"[gadget] Tree: {tree}")

    search_dirs = [out, src.parent if src.is_file() else src, Path.cwd()]
    config_file = resolve_config_path(
        config_path,
        search_dirs,
        out,
        input_fn=input_fn,
        output_fn=output_fn,
        auto_confirm=auto_confirm,
    )
    output_fn(f"[gadget] Config: {config_file}")

    kind, hooks, raw_config = load_hook_config(config_file)

    if kind == "gadget":
        gadget_config_text = json.dumps(raw_config, ensure_ascii=False, indent=2)
        script_path = Path(str(raw_config.get("interaction", {}).get("path", "")))
        if script_path.is_absolute() and script_path.exists():
            script_text = script_path.read_text(encoding="utf-8", errors="replace")
        else:
            sibling = config_file.parent / script_path.name if script_path.name else None
            if sibling and sibling.exists():
                script_text = sibling.read_text(encoding="utf-8", errors="replace")
            else:
                script_text = "// PatchX Gadget script\n"
    else:
        fallback_script = config_file.parent / "generated_hook.js"
        script_text = combine_hook_scripts(hooks, fallback=fallback_script)
        if gadget_mode == "listen":
            gadget_config_text = json.dumps(
                {
                    "interaction": {
                        "type": "listen",
                        "address": "127.0.0.1",
                        "port": 27042,
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
        else:
            gadget_config_text = json.dumps(
                {
                    "interaction": {
                        "type": "script",
                        "path": "libgadget.script.so",
                    }
                },
                ensure_ascii=False,
                indent=2,
            )

    output_fn("[gadget] Thuc thi cau hinh smali...")
    smali_result = apply_smali_config(tree, hooks) if hooks else {"success": 0, "failed": 0, "skipped": 0, "details": []}

    output_fn("[gadget] Cap nhat manifest...")
    manifest_ok = set_extract_native_libs(tree)

    output_fn("[gadget] Nap gadget...")
    if gadget_path:
        gadget_so = Path(gadget_path).expanduser().resolve()
        if not gadget_so.exists():
            raise FileNotFoundError(f"Khong tim thay gadget: {gadget_so}")
    else:
        gadget_so = download_gadget(out / "libgadget.so", url=gadget_url)

    embed_result = embed_gadget(tree, gadget_so, gadget_config_text, script_text)

    output_fn("[gadget] Chen loader System.loadLibrary...")
    loader_result = inject_gadget_loader(tree)

    output_fn("[gadget] Chay apk-fix-res...")
    resource_fix = _normalize_gadget_resources(tree)
    output_fn(f"[gadget] Resource fixes: {resource_fix.get('changes', 0)}")

    output_fn("[gadget] Dong goi va ky APK...")
    build_result = build_and_sign(tree, out, sign=sign, keystore=keystore, ks_pass=ks_pass)

    return {
        "ok": bool(build_result.get("ok")) and loader_result.get("ok"),
        "input": str(src),
        "tree": str(tree),
        "decoded": decoded,
        "config": str(config_file),
        "smali_result": smali_result,
        "manifest_ok": manifest_ok,
        "embedded": embed_result,
        "loader": loader_result,
        "resource_fix": resource_fix,
        "build": build_result,
    }
