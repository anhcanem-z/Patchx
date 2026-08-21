from __future__ import annotations

import argparse
import json
from pathlib import Path

from .detector import BehaviorDetector
from .frida_generator import FridaScriptGenerator
from .patcher import SmaliPatcher
from .pipeline import run_frida_pipeline
from .target import TargetAnalyzer


def main():
    parser = argparse.ArgumentParser(
        description="Chuong trinh phan tich va tu dong tao phuong an Bypass APK (Smali & Frida)."
    )
    parser.add_argument("decompiled_dir", help="Duong dan toi thu mức APK da giai ma (qua apktool).")
    parser.add_argument("--auto-patch", action="store_true", help="Tu dong ap dung Patch truc tiep vao file Smali.")
    parser.add_argument("--gen-frida", default="agent.js", help="Duong dan file Frida JS dau ra (mac dinh: agent.js).")
    parser.add_argument("--output-report", default="report.json", help="Duong dan xuat bao cao JSON.")
    parser.add_argument("--pipeline", action="store_true", help="Chay luong detector -> cfg -> target -> hook -> frida -> loader -> APK.")
    parser.add_argument("-o", "--out-dir",
                    default=str(Path(__file__).resolve().parents[2] / "outputs" / "behavior"),
                    help="Thu mức xuat artifact khi chay pipeline.")
    parser.add_argument("--build-apk", action="store_true", help="Build APK sau khi sua (chi dung voi --pipeline).")
    parser.add_argument("--interactive", action="store_true", help="Hien goi y va cho nguoi dung chon target trước khi thuc hien.")
    parser.add_argument("--min-score", type=float, default=0.65, help="Nguong diem bypass toi thieu cho target (mac dinh 0.65).")

    args = parser.parse_args()
    root_dir = Path(args.decompiled_dir)

    if args.pipeline:
        if not root_dir.exists():
            print(f"[!] Thu mức khong ton tai: {root_dir}")
            return 1

        report = run_frida_pipeline(
            root_dir,
            out_dir=args.out_dir,
            auto_patch=args.auto_patch,
            build_apk=args.build_apk,
            min_score=args.min_score,
            interactive=args.interactive,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1

    if not root_dir.exists():
        print(f"[!] Thu mức khong ton tai: {root_dir}")
        return 1

    print(f"[*] Bat dau quet thu mức: {root_dir}")

    # 1. Quet hanh vi
    detector = BehaviorDetector(root_dir)
    behaviors = detector.scan()
    print(f"[+] Tim thay {len(behaviors)} nhóm hanh vi.")

    # 2. Phan tich mức tieu & tao chien luoc
    analyzer = TargetAnalyzer(root_dir)
    targets = analyzer.analyze(behaviors)
    print(f"[+] Xac dinh duoc {len(targets)} điểm mức tieu (Targets).")

    # 3. Tu dong Patch Smali (neu duoc yeu cau)
    patch_stats = {}
    if args.auto_patch:
        print("[*] Dang tien hanh tu dong Patch Smali...")
        patcher = SmaliPatcher(root_dir)
        patch_stats = patcher.apply_targets(targets)
        print(f"[+] Da Patch thanh cong {patch_stats.get('success', 0)} điểm.")

    # 4. Tao Frida Script
    print(f"[*] Dang xuat Frida Script toi '{args.gen_frida}'...")
    frida_gen = FridaScriptGenerator()
    frida_script = frida_gen.generate(targets, output_file=args.gen_frida)

    # 5. Xuat bao cao JSON
    report_data = {
        "stats": detector.get_stats(),
        "patch_stats": patch_stats,
        "behaviors": [b.to_dict() for b in behaviors],
        "targets": [t.to_dict() for t in targets],
    }

    Path(args.output_report).write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[+] Bao cao hoan tat va luu tai: {args.output_report}")


if __name__ == "__main__":
    main()
