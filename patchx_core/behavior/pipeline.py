from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .detector import BehaviorDetector
from .frida_generator import FridaScriptGenerator
from .patcher import SmaliPatcher
from .target import TargetAnalyzer


SCHEMA_PIPELINE = "patchx.behavior-pipeline/v1"
SCHEMA_LOADER = "patchx.frida-loader/v1"


def read_manifest_package(tree: str | Path, default: str = "com.example.app") -> str:
    """Doc package goc tu AndroidManifest.xml neu co."""
    manifest = Path(tree) / "AndroidManifest.xml"
    if not manifest.exists():
        return default

    try:
        text = manifest.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return default

    match = re.search(r"\bpackage\s*=\s*[\"']([^\"']+)[\"']", text)
    if not match:
        match = re.search(r"\bpackage\s*:\s*[\"']([^\"']+)[\"']", text)

    return match.group(1) if match else default


def extract_cfg_artifacts(behaviors: List[Any]) -> List[Dict[str, Any]]:
    """Trich cac bang chung CFG ma detector da sinh de lam mot stage tuong minh."""
    artifacts: List[Dict[str, Any]] = []

    for behavior in behaviors:
        for evidence in behavior.evidence:
            if evidence.kind != "cfg-branch-analysis":
                continue

            details = dict(evidence.details or {})
            artifacts.append(
                {
                    "behavior": behavior.name,
                    "method": details.get("method", ""),
                    "api": details.get("api", ""),
                    "branch": details.get("branch", ""),
                    "api_line": details.get("api_line"),
                    "branch_line": details.get("branch_line"),
                    "block_id": details.get("block_id"),
                    "successors": details.get("successors", []),
                }
            )

    return artifacts


def write_json(path: str | Path, data: Dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_apk_from_tree(tree: str | Path, out_apk: str | Path) -> Dict[str, Any]:
    """Build APK tu cây da patch. Tra ve trang thai, khong nem lỗi neu thieu cong cu."""
    apktool = shutil.which("apktool")
    if not apktool:
        return {
            "ok": False,
            "apk": None,
            "error": "Khong tim thay apktool; bo qua buoc build APK.",
        }

    out = Path(out_apk)
    out.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [apktool, "b", str(tree), "-o", str(out)],
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        return {
            "ok": False,
            "apk": str(out),
            "error": (proc.stderr or proc.stdout or "").strip()[-2000:],
        }

    return {
        "ok": True,
        "apk": str(out),
        "signed": False,
        "note": "APK chua ky/zipalign. Dung apksigner neu can cai truc tiep.",
    }


def generate_loader_js(path: str | Path) -> str:
    """Ghi frida_loader.js doc loader_hook.json va thuc thi cac rule hook."""
    loader = """// frida_loader.js
const fs = require('fs');
const path = require('path');

function loadPipeline(manifestPath) {
    if (!manifestPath) {
        manifestPath = 'loader_hook.json';
    }

    const manifestPathAbs = path.resolve(manifestPath);
    const manifest = JSON.parse(fs.readFileSync(manifestPathAbs, 'utf8'));
    const hookConfigPath = path.resolve(path.dirname(manifestPathAbs), manifest.hook_config);
    const config = JSON.parse(fs.readFileSync(hookConfigPath, 'utf8'));
    const rules = Array.isArray(config.hooks) ? config.hooks : [];

    console.log('[*] Package: ' + (manifest.package || config.metadata.target_package));
    console.log('[*] Hook config: ' + hookConfigPath);
    console.log('[*] Total rules: ' + rules.length);

    rules.forEach(function (rule) {
        if (!rule.enabled) {
            return;
        }

        console.log('[+] Executing rule ' + rule.id + ' (' + rule.category + ')');
        try {
            if (rule.frida_script) {
                eval(rule.frida_script);
            }
        } catch (err) {
            console.error('[-] Failed to eval rule ' + rule.id + ': ' + err.message);
        }
    });
}

if (require.main === module) {
    loadPipeline(process.argv[2]);
}

module.exports = { loadPipeline: loadPipeline };
"""
    Path(path).write_text(loader, encoding="utf-8")
    return loader


def embed_frida_assets(
    tree_path: str | Path,
    hook_config_path: str | Path,
    frida_script_path: str | Path,
    loader_config_path: str | Path,
    loader_js_path: str | Path,
) -> Dict[str, Any]:
    """Nhung cac file cau hinh Frida vao assets cua cay APK de dong goi cung APK."""
    assets_dir = Path(tree_path) / "assets" / "patchx_frida"
    assets_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for src in (hook_config_path, frida_script_path, loader_config_path, loader_js_path):
        src_path = Path(src)
        if not src_path.exists():
            continue
        shutil.copy2(src_path, assets_dir / src_path.name)
        copied.append(str(assets_dir / src_path.name))

    return {
        "assets_dir": str(assets_dir),
        "files": copied,
    }


def _print_review_list(items: List[Dict[str, Any]], output_fn=print) -> None:
    output_fn("\nDanh sach hanh vi de xuat thay doi:")
    for idx, item in enumerate(items, 1):
        cfg_mark = " | CFG" if item.get("cfg_backed") else ""
        output_fn(
            f"[{idx}] {item.get('category')} "
            f"({item.get('confidence', 0):.2f} conf / "
            f"{item.get('evidence_score', 0):.2f} score / "
            f"{item.get('evidence_count', 0)} evidence{cfg_mark})"
        )
        target_name = f"{item.get('class')}->{item.get('method') or '?'}"
        output_fn(f"    {target_name} :: {item.get('reason')}")
        for suggestion in item.get("suggestions", [])[:3]:
            output_fn(f"      - {suggestion}")


def _select_review_items(
    ranked_targets: List[Any],
    items: List[Dict[str, Any]],
    input_fn=input,
    output_fn=print,
) -> List[Any]:
    if not items:
        output_fn("\nKhong co target du manh de duyet.")
        return []

    _print_review_list(items, output_fn=output_fn)
    output_fn("\nNhap so can thay doi (vd: 1,3,5), `all`, hoac `q` de bo qua:")

    raw = input_fn("> ").strip()
    if raw.lower() == "q":
        return []
    if raw.lower() == "all":
        return list(ranked_targets)

    selected: List[Any] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            index = int(part) - 1
        except ValueError:
            continue
        if 0 <= index < len(ranked_targets):
            selected.append(ranked_targets[index])
    return selected


def _execute_targets(
    tree_path: Path,
    targets: List[Any],
    out_path: Path,
    package: str,
    cfg_artifacts: List[Dict[str, Any]],
    stats: Dict[str, Any],
    *,
    auto_patch: bool,
    build_apk: bool,
    embed_frida: bool = False,
) -> Dict[str, Any]:
    analyzer = TargetAnalyzer(tree_path)

    hook_config_path = out_path / "frida_hooks_config.json"
    analyzer.export_frida_json(targets, hook_config_path, app_package=package)

    frida_script_path = out_path / "generated_hook.js"
    FridaScriptGenerator().generate(targets, output_file=frida_script_path)

    loader_config_path = out_path / "loader_hook.json"
    loader_config = {
        "schema": SCHEMA_LOADER,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "package": package,
        "tree": str(tree_path),
        "hook_config": hook_config_path.name,
        "frida_script": frida_script_path.name,
        "total_targets": len(targets),
        "total_cfg_artifacts": len(cfg_artifacts),
        "stats": stats,
        "commands": {
            "frida": f"frida -U -f {package} -l {frida_script_path} --no-pause",
            "node_loader": f"node {out_path / 'frida_loader.js'} {loader_config_path}",
        },
    }
    write_json(loader_config_path, loader_config)

    loader_js_path = out_path / "frida_loader.js"
    generate_loader_js(loader_js_path)

    embedded_frida = None
    if embed_frida and targets:
        embedded_frida = embed_frida_assets(
            tree_path,
            hook_config_path,
            frida_script_path,
            loader_config_path,
            loader_js_path,
        )

    patch_result = None
    if auto_patch and targets:
        patcher = SmaliPatcher(tree_path)
        patch_result = patcher.apply_targets(targets)

    build_result = None
    if build_apk and targets:
        build_result = build_apk_from_tree(tree_path, out_path / "app.apk")

    return {
        "hook_config": str(hook_config_path),
        "frida_script": str(frida_script_path),
        "loader_config": str(loader_config_path),
        "loader_js": str(loader_js_path),
        "embedded_frida": embedded_frida,
        "patch_result": patch_result,
        "build_result": build_result,
    }


def run_frida_pipeline(
    tree: str | Path,
    out_dir: str | Path = "outputs/behavior",
    package: Optional[str] = None,
    *,
    auto_patch: bool = False,
    build_apk: bool = False,
    min_score: float = 0.65,
    interactive: bool = False,
    input_fn=input,
    output_fn=print,
    behavior_filter: Optional[set[str]] = None,
    embed_frida: bool = False,
) -> Dict[str, Any]:
    """Chay luong:

    detector -> cfg -> target -> rank/review -> hook.json -> frida -> loader -> (APK tuy chon)
    """
    tree_path = Path(tree).expanduser().resolve()
    if not tree_path.is_dir():
        raise FileNotFoundError(f"Khong tim thay cây APK: {tree_path}")

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    package = package or read_manifest_package(tree_path)
    started = time.time()

    # 1. Detector: quet hanh vi va sinh bang chung.
    detector = BehaviorDetector(tree_path)
    behaviors = detector.scan()

    if behavior_filter is not None:
        behaviors = [b for b in behaviors if b.name in behavior_filter]

    # 2. CFG: tach cac artifact nhanh da duoc detector dung qua build_cfg.
    cfg_artifacts = extract_cfg_artifacts(behaviors)

    # 3. Target: bien behavior + CFG thanh target cu the.
    analyzer = TargetAnalyzer(tree_path)
    targets = analyzer.analyze(behaviors)

    # 4. Rank target: chi giu target co bang chung manh, da gom theo method.
    ranked_targets = analyzer.rank_targets(targets, min_score=min_score)
    review_items = [target.to_review_dict() for target in ranked_targets]
    write_json(
        out_path / "review_plan.json",
        {
            "schema": "patchx.target-review/v1",
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "package": package,
            "tree": str(tree_path),
            "min_score": min_score,
            "targets": review_items,
        },
    )

    # 5. Nguoi dung duyet/chon neu chay interactive.
    final_targets = ranked_targets
    if interactive:
        final_targets = _select_review_items(
            ranked_targets,
            review_items,
            input_fn=input_fn,
            output_fn=output_fn,
        )

    # 6. Thuc hien theo lua chon: hook.json -> frida -> loader -> APK.
    executed = _execute_targets(
        tree_path,
        final_targets,
        out_path,
        package,
        cfg_artifacts,
        detector.get_stats(),
        auto_patch=auto_patch,
        build_apk=build_apk,
        embed_frida=embed_frida,
    )

    result: Dict[str, Any] = {
        "schema": SCHEMA_PIPELINE,
        "ok": True,
        "package": package,
        "tree": str(tree_path),
        "out_dir": str(out_path),
        "behaviors": [b.to_dict() for b in behaviors],
        "cfg_artifacts": cfg_artifacts,
        "targets": [t.to_dict() for t in final_targets],
        "review_items": review_items,
        "artifacts": executed,
        "stats": detector.get_stats(),
        "elapsed_seconds": round(time.time() - started, 3),
    }

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Pipeline hanh vi PatchX: detector -> cfg -> target -> hook -> frida -> loader -> APK"
    )
    parser.add_argument("tree", help="Thư mục APK đã giải mã")
    parser.add_argument("-o", "--out-dir", default="outputs/behavior", help="Thư mục đầu ra")
    parser.add_argument("--package", default=None, help="Ten package (tu doc Manifest neu bo trong)")
    parser.add_argument("--auto-patch", action="store_true", help="Sua Smali truc tiep vao cây APK")
    parser.add_argument("--build-apk", action="store_true", help="Build APK sau khi sua (can apktool)")
    args = parser.parse_args()

    report = run_frida_pipeline(
        args.tree,
        out_dir=args.out_dir,
        package=args.package,
        auto_patch=args.auto_patch,
        build_apk=args.build_apk,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
