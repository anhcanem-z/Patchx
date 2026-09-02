# -*- coding: utf-8 -*-
"""UI CLI tieng Viet cho PATCHX, dung duoc tren Termux khong can curses.

UI nay la lop dieu huong cho cac thao tac quan sat. No khong goi Engine.apply,
khong sinh patch va khong tu chay lệnh co ghi du lieu. Cac tac vu thay doi van
phai chay bang CLI goc voi tham so tuong minh va buoc duyet cua nguoi dung.
"""

import json
import os
import sys


MENU = (
    ("1", "Xem ban do van hanh", "Hien nhóm thu mức va duong dan nguon that."),
    ("2", "Xem trang thai V2", "Doc so lieu acceptance fixture, khong sua du lieu."),
    ("3", "Tom tat kho patch", "Dem patch chuan hoa va patch nang cao, chi doc."),
    ("4", "Huong dan luong an toan", "In cac lệnh V2 va cac gate bat buoc."),
    ("0", "Thoat", "Khong thuc hien thay doi."),
)


class TerminalUI:
    """Menu van ban nho, tach I/O de co the kiem thu khong tuong tac."""

    def __init__(self, root, input_fn=input, output_fn=print):
        self.root = os.path.abspath(root)
        self.input = input_fn
        self.output = output_fn

    def _line(self, value=""):
        self.output(value)

    def render_header(self):
        self._line("=" * 62)
        self._line("PATCHX — GIAO DIỆN CLI TIẾNG VIỆT")
        self._line("Che do an toan: chi doc; khong tu ap patch hoac tao APK.")
        self._line("=" * 62)

    def render_menu(self):
        self.render_header()
        for key, title, detail in MENU:
            self._line("[%s] %-27s %s" % (key, title, detail))

    def navigation(self):
        """Hien mapping van hanh; target thieu duoc danh dau ro rang."""
        path = os.path.join(self.root, "OPERATIONS", "NAVIGATION.json")
        if not os.path.isfile(path):
            self._line("Khong thay OPERATIONS/NAVIGATION.json.")
            return 1
        try:
            with open(path, encoding="utf-8") as fh:
                nav = json.load(fh)
        except (OSError, ValueError) as exc:
            self._line("Khong doc duoc ban do van hanh: %s" % exc)
            return 1
        groups = nav.get("groups", [])
        total = sum(len(group.get("targets", [])) for group in groups)
        missing = 0
        self._line("\nBẢN ĐỒ VẬN HÀNH — %d nhóm, %d liên kết" % (len(groups), total))
        for group in groups:
            self._line("- %s: %s" % (group.get("id", "?"),
                                      group.get("role", "Khong mo ta")))
            for target in group.get("targets", []):
                full = os.path.normpath(os.path.join(self.root, "OPERATIONS", target))
                ok = os.path.exists(full)
                missing += 0 if ok else 1
                self._line("    %s %s" % ("✓" if ok else "✗", target))
        self._line("Kết quả liên kết: %s" % ("PASS" if not missing
                                               else "FAIL — thiếu %d target" % missing))
        return 0 if not missing else 1

    def v2_status(self):
        """Chay acceptance fixture V2; chi doc fixtures."""
        from .acceptance import run_acceptance
        fixture = os.path.join(self.root, "tests", "fixtures", "semantic_v2")
        try:
            report = run_acceptance(fixture)
        except (OSError, ValueError) as exc:
            self._line("Khong chay duoc acceptance V2: %s" % exc)
            return 1
        metrics = report.get("metrics", {})
        self._line("\nTRANG THAI V2")
        self._line("- Tai lap model: %.2f%%" % report["reproducibility"]["rate"])
        self._line("- Tai nhan dien: %.2f%%" % (report.get("reidentification_rate") or 0))
        self._line("- READY dung: %d/%d" % (metrics.get("ready_ok", 0),
                                             metrics.get("ready_total", 0)))
        self._line("- Duong tinh gia: %.2f%%" % metrics.get("false_positive_rate", 0))
        self._line("- Mo ho bi chan: %d/%d" % (metrics.get("ambiguity_blocked", 0),
                                                metrics.get("ambiguity_total", 0)))
        self._line("Ket qua: chi la evidence; nguoi dung van duyet trước preflight.")
        return 0

    def patch_summary(self):
        """Dem zip hai kho patch chinh, khong parse/ghi noi dung."""
        roots = (("Patch chuan hoa", "upgraded"),
                 ("Patch nang cao", "bypass_plus"),
                 ("Combo chinh", "combos"),
                 ("Combo tu dong", "combos_auto"))
        self._line("\nTOM TAT KHO PATCH")
        for label, rel in roots:
            path = os.path.join(self.root, rel)
            count = 0
            if os.path.isdir(path):
                count = sum(1 for name in os.listdir(path)
                            if name.lower().endswith((".zip", ".patch")))
            self._line("- %-18s %d tệp" % (label + ":", count))
        self._line("Goi y: dung `patchx scan upgraded --recursive` de xem chi tiet.")
        return 0

    def safe_workflow(self):
        self._line("\nLUONG V2 AN TOAN")
        self._line("1. patchx model CAY_APK --v2")
        self._line("2. patchx semantic-plan CAY_APK PLAN.json --verbose")
        self._line("3. patchx plan-compile CAY_APK PLAN.json -o DRAFT.json")
        self._line("4. Nguoi dung duyet draft → preflight → validate → build → runtime")
        self._line("Dung ngay khi evidence thieu, target mo ho hoac gate that bai.")
        return 0

    def execute(self, choice):
        actions = {"1": self.navigation, "2": self.v2_status,
                   "3": self.patch_summary, "4": self.safe_workflow}
        action = actions.get(choice)
        if action is None:
            self._line("Lựa chọn không hợp lệ. Nhập 0–4.")
            return None
        return action()

    def run_demo(self):
        """Hien man hinh dau va ban do, phu hop CI/non-interactive."""
        self.render_menu()
        return self.navigation()

    def run(self):
        self.render_menu()
        while True:
            try:
                choice = self.input("\nChon chuc nang [0-4]: ").strip()
            except (EOFError, KeyboardInterrupt):
                self._line("\nĐã thoát UI CLI.")
                return 0
            if choice == "0":
                self._line("Đã thoát UI CLI. Không có dữ liệu nào bị thay đổi.")
                return 0
            self.execute(choice)


def run_terminal_ui(root, demo=False, input_fn=input, output_fn=print):
    """Diem vao dung boi CLI va test; ``demo`` khong yeu cau TTY."""
    ui = TerminalUI(root, input_fn=input_fn, output_fn=output_fn)
    if demo:
        return ui.run_demo()
    if not sys.stdin.isatty():
        output_fn("UI CLI can terminal tuong tac. Dung `patchx ui --demo` de xem trước.")
        return 2
    return ui.run()
