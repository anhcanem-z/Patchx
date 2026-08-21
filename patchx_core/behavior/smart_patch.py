# -*- coding: utf-8 -*-
"""smart-patch — bản patch thông minh cho smali, tái sử dụng detector có sẵn.

Luồng (không tạo từ điển mới — dùng đúng BehaviorDetector/TargetAnalyzer/
SmaliPatcher trong behavior):

    detector -> target -> rank -> kế hoạch (JSON+MD) -> [--apply] backup + patch

Detector đã có sẵn nhánh obfuscation cho R8/D8 (OBFUSCATED_NAME_RE + các kind
obfuscated-feature-unlock / obfuscated-billing-flow / obfuscated-ssl-pinning /
obfuscated-api-flow...); smart-patch chỉ gắn nhãn R8/D8 cho từng target dựa
trên chính cờ/details của detector, rồi áp patch_mode do TargetAnalyzer sinh.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from .detector import BehaviorDetector
from .target import TargetAnalyzer, target_bypass_score
from .patcher import SmaliPatcher

SCHEMA = "patchx.smart-patch/v1"

# Đúng quy tắc tên obfuscated R8/D8 mà detector đã dùng (OBFUSCATED_NAME_RE).
R8_NAME_RE = re.compile(r"^[a-zA-Z]{1,3}$|^[a-zA-Z]\d{0,2}$")

# R8 giữ nguyên các class này — không coi là obfuscated.
NON_OBFUSCATED_TAIL = {"R", "BuildConfig"}


def _is_r8_name(name: str) -> bool:
    return bool(name) and bool(R8_NAME_RE.match(name))


def _is_r8_class(class_name: str) -> bool:
    clean = (class_name or "").strip()
    if clean.startswith("L") and clean.endswith(";"):
        clean = clean[1:-1]
    clean = clean.replace("/", ".").replace("\\", ".")
    tail = clean.split(".")[-1]
    if tail in NON_OBFUSCATED_TAIL:
        return False
    return _is_r8_name(tail)


def _annotate(target) -> dict[str, Any]:
    """Chuyen Target thanh dict + gắn nhãn R8/D8 từ chính detector/target."""
    auto = target.suggested_actions.get("auto_strategy", {})
    kind = ""
    weight = 0.0
    for ev in target.evidence:
        kind = ev.get("kind", "")
        weight = float(ev.get("weight", 0.0))
        break
    name_obf = _is_r8_name(target.method)
    class_obf = _is_r8_class(target.class_name)
    hookable = bool(target.is_frida_hookable()) \
        if hasattr(target, "is_frida_hookable") else False
    return {
        "category": target.category,
        "source": target.source,
        "class_name": target.class_name,
        "method": target.method,
        "patch_mode": auto.get("patch_mode", ""),
        "r8_d8": bool(name_obf or class_obf or kind.startswith("obfuscated-")),
        "obfuscated_name": name_obf,
        "obfuscated_class": class_obf,
        "kind": kind,
        "weight": weight,
        "score": target_bypass_score(target),
        "frida_hookable": hookable,
        "reason": target.reason,
    }


def _detect_and_rank(tree, min_score: float, behavior_filter: Optional[set[str]]):
    """Detector + TargetAnalyzer có sẵn -> (tree_path, behaviors, raw, ranked)."""
    tree_path = Path(tree).expanduser().resolve()
    if not tree_path.is_dir():
        raise FileNotFoundError("Khong tim thay cây APK: %s" % tree_path)
    detector = BehaviorDetector(str(tree_path))
    behaviors = detector.scan()
    if behavior_filter is not None:
        behaviors = [b for b in behaviors if b.name in behavior_filter]
    analyzer = TargetAnalyzer(str(tree_path))
    raw = analyzer.analyze(behaviors)
    ranked = analyzer.rank_targets(raw, min_score=min_score)
    return tree_path, behaviors, raw, ranked


def build_smart_plan(tree, min_score: float = 0.65,
                     behavior_filter: Optional[set[str]] = None) -> dict[str, Any]:
    """Lập kế hoạch patch thông minh (chỉ đọc, không ghi smali)."""
    tree_path, behaviors, raw, ranked = _detect_and_rank(
        tree, min_score, behavior_filter)
    targets = [_annotate(t) for t in ranked]
    return {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tree": str(tree_path),
        "min_score": min_score,
        "behaviors": [
            {"name": b.name, "confidence": round(b.confidence, 4),
             "evidence": len(b.evidence)} for b in behaviors
        ],
        "targets": targets,
        "stats": {
            "behaviors": len(behaviors),
            "targets_raw": len(raw),
            "targets_ranked": len(targets),
            "r8_d8_targets": sum(1 for t in targets if t["r8_d8"]),
        },
    }


def render_plan_markdown(plan: dict[str, Any]) -> str:
    """Báo cáo Markdown kế hoạch (tiếng Việt, có dấu)."""
    stats = plan["stats"]
    lines = [
        "# Bản patch thông minh — smali (ngữ nghĩa + chống R8/D8)", "",
        "- Cây APK: `%s`" % plan["tree"],
        "- Ngưỡng điểm: %.2f" % plan["min_score"],
        "- Hành vi: %d | Target thô: %d | Target chọn: %d | R8/D8: %d" % (
            stats["behaviors"], stats["targets_raw"], stats["targets_ranked"],
            stats["r8_d8_targets"]),
        "",
    ]
    if plan["behaviors"]:
        lines += ["## Hành vi phát hiện (từ điển behavior)", "",
                  "| Hành vi | Độ tin cậy | Bằng chứng |",
                  "|---|---:|---:|"]
        for b in plan["behaviors"]:
            lines.append("| %s | %.1f%% | %d |"
                         % (b["name"], b["confidence"] * 100, b["evidence"]))
        lines.append("")
    lines += ["## Target đề xuất", "",
              "| # | Nhóm | Tệp | Phương thức | R8/D8 | Chiến lược | Điểm |",
              "|---|---|---|---|---|---:|---:|"]
    for i, t in enumerate(plan["targets"], 1):
        lines.append("| %d | %s | `%s` | %s | %s | %s | %.3f |" % (
            i, t["category"], t["source"], t["method"] or "—",
            "có" if t["r8_d8"] else "không",
            t["patch_mode"] or "—", t["score"]))
    lines.append("")
    return "\n".join(lines)


def _backup_files(tree_path: Path, sources, backup_dir: Path) -> list[str]:
    """Backup từng file smali trước khi ghi (giữ cấu trúc tương đối)."""
    created = []
    for src in sources:
        src_path = Path(src)
        try:
            rel = src_path.relative_to(tree_path)
        except ValueError:
            rel = Path(src_path.name)
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst)
        created.append(str(dst))
    return created


def apply_smart_patch(tree, out_dir, min_score: float = 0.65,
                      apply: bool = False,
                      behavior_filter: Optional[set[str]] = None
                      ) -> dict[str, Any]:
    """Chạy smart-patch: lập kế hoạch; --apply ghi smali sau khi backup."""
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    tree_path, behaviors, raw, ranked = _detect_and_rank(
        tree, min_score, behavior_filter)
    plan = {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tree": str(tree_path),
        "min_score": min_score,
        "behaviors": [
            {"name": b.name, "confidence": round(b.confidence, 4),
             "evidence": len(b.evidence)} for b in behaviors
        ],
        "targets": [_annotate(t) for t in ranked],
        "stats": {
            "behaviors": len(behaviors),
            "targets_raw": len(raw),
            "targets_ranked": len(ranked),
            "r8_d8_targets": sum(1 for t in ranked
                                 if _annotate(t)["r8_d8"]),
        },
    }
    (out_path / "smart_patch_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_path / "smart_patch_plan.md").write_text(
        render_plan_markdown(plan) + "\n", encoding="utf-8")

    patched = None
    if apply and ranked:
        sources = []
        seen = set()
        for t in ranked:
            src = t.source
            if src and src not in seen:
                seen.add(src)
                sources.append(src)
        backup_dir = out_path / "backup"
        backup_files = _backup_files(tree_path, sources, backup_dir)
        result = SmaliPatcher(str(tree_path)).apply_targets(ranked)
        patched = {
            "success": result["success"],
            "failed": result["failed"],
            "details": result["details"],
            "backup_dir": str(backup_dir),
            "backup_files": backup_files,
        }

    report = {
        "schema": SCHEMA,
        "generated": plan["generated"],
        "tree": str(tree_path),
        "plan": plan,
        "patched": patched,
    }
    (out_path / "smart_patch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = render_plan_markdown(plan)
    if patched:
        md += "\n## Kết quả áp patch\n\n"
        md += "- Thành công: %d | Lỗi: %d\n" % (patched["success"],
                                                patched["failed"])
        md += "- Backup: `%s`\n\n" % patched["backup_dir"]
        md += "| Tệp | Trạng thái | Chiến lược |\n|---|---|---|\n"
        for d in patched["details"]:
            md += "| `%s` | %s | %s |\n" % (d["file"], d["status"],
                                             d.get("mode", ""))
        md += "\n"
    (out_path / "smart_patch_report.md").write_text(md, encoding="utf-8")
    return report
