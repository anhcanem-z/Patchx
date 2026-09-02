# -*- coding: utf-8 -*-
"""sync_modules — KIỂM TRA ĐỒNG BỘ module khi thêm tính năng / nâng cấp.

Chạy:  python3 tools/sync_modules.py

Rà:
  1. Lệnh trong cli.py (add_parser)  ↔  3 file HUONG_DAN_*.txt
  2. Module behavior/ mới            ↔  test tương ứng trong tests/run_tests.py
  3. Kho hành vi đã học
     (outputs/behavior/discovered/)  ↔  từ điển gốc SMART_BEHAVIORS
  4. mtime code patchx_core/         ↔  AGENTS_TRANG_THAI.md

Chỉ IN thiếu sót, KHÔNG tự sửa file.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "patchx_core", "cli.py")
BEHAVIOR_DIR = os.path.join(ROOT, "patchx_core", "behavior")
TESTS = os.path.join(ROOT, "tests", "run_tests.py")
STATE = os.path.join(ROOT, "AGENTS_TRANG_THAI.md")
ONTOLOGY = os.path.join(ROOT, "patchx_core", "behavior", "smart_ontology.py")
DISCOVERED = os.path.join(ROOT, "outputs", "behavior", "discovered",
                          "behaviors.json")
DOCS = [
    os.path.join(ROOT, "HUONG_DAN_LENH.txt"),
    os.path.join(ROOT, "HUONG_DAN_BEHAVIOR_FRIDA.txt"),
    os.path.join(ROOT, "HUONG_DAN_GADGET.txt"),
]


def commands_in_cli() -> list:
    if not os.path.isfile(CLI):
        return []
    text = open(CLI, encoding="utf-8").read()
    return re.findall(r'add_parser\(\s*"([A-Za-z0-9_-]+)"', text)


def main() -> int:
    warns = []

    # 1) Lệnh cli.py ↔ tài liệu
    cmds = commands_in_cli()
    docs_text = "\n".join(open(d, encoding="utf-8").read()
                          for d in DOCS if os.path.isfile(d))
    docless = [c for c in cmds
               if c not in docs_text and c not in
               ("menu", "ui", "frida", "stats", "clean")]
    if docless:
        warns.append("Lệnh chưa có trong HUONG_DAN_*.txt: %s"
                     % ", ".join(sorted(docless)))

    # 2) Module behavior ↔ test
    tests_text = open(TESTS, encoding="utf-8").read() if os.path.isfile(TESTS) else ""
    missing_tests = []
    if os.path.isdir(BEHAVIOR_DIR):
        for f in sorted(os.listdir(BEHAVIOR_DIR)):
            if not f.endswith(".py") or f.startswith("__"):
                continue
            mod = f[:-3]
            if mod in ("smart_ontology", "behavior_learner"):
                continue
            if ("test_%s" % mod) not in tests_text and \
               ("%s" % mod) not in tests_text:
                missing_tests.append(mod)
    if missing_tests:
        warns.append("Module behavior/ chưa có test trong run_tests.py: %s"
                     % ", ".join(missing_tests))

    # 3) Kho hành vi đã học ↔ từ điển gốc
    if os.path.isfile(DISCOVERED):
        try:
            store = json.load(open(DISCOVERED, encoding="utf-8"))
            onto = open(ONTOLOGY, encoding="utf-8").read() if os.path.isfile(ONTOLOGY) else ""
            unmerged = [bid for bid in store
                        if ("\"%s\"" % bid) not in onto]
            if unmerged:
                warns.append("Hành vi đã học chưa merge vào SMART_BEHAVIORS: %s"
                             % ", ".join(sorted(unmerged)))
        except Exception as exc:
            warns.append("Không đọc được kho discovered: %s" % exc)

    # 4) mtime code ↔ AGENTS_TRANG_THAI.md
    state_mtime = os.path.getmtime(STATE) if os.path.isfile(STATE) else 0
    newer = []
    for root, _dirs, files in os.walk(os.path.join(ROOT, "patchx_core")):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(root, f)
                if os.path.getmtime(p) > state_mtime + 2:
                    newer.append(os.path.relpath(p, ROOT))
    if newer:
        warns.append("Code mới hơn AGENTS_TRANG_THAI.md (chưa cập nhật trạng "
                     "thái): %s" % ", ".join(sorted(newer)[:6]))

    print("=== sync_modules — KIỂM TRA ĐỒNG BỘ ===")
    print("Lệnh cli.py: %d | Module behavior: %d | Kho discovered: %s"
          % (len(cmds),
             len([f for f in os.listdir(BEHAVIOR_DIR)
                  if f.endswith(".py") and not f.startswith("__")])
             if os.path.isdir(BEHAVIOR_DIR) else 0,
             "có" if os.path.isfile(DISCOVERED) else "chưa có"))
    if warns:
        print("\nCẦN BỔ SUNG (%d):" % len(warns))
        for w in warns:
            print("  - %s" % w)
        return 1
    print("\nOK — mọi module đã đồng bộ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
