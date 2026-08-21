# -*- coding: utf-8 -*-
"""Baseline & do luong (PHASE 0 — PATCHX V2).

Dong bang thuoc do co dinh: baseline/metrics.json + so sanh hoi quy.
Moi thay doi phai duoc so voi baseline trước khi chap nhan
(Rule 5: khong toi uu trước khi co baseline).
"""

import json
import os
import platform
import re
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASELINE_DIR = os.path.join(BASE_DIR, "outputs", "baseline")

# Dinh nghia cac chi so: trend = "higher" (cang cao cang tot) hay
# "lower" (cang thap cang tot); threshold = do xau di cho phep trước
# khi bi coi la hoi quy (don vi cua chinh chi so; 0 = moi xau di deu chan).
METRICS = {
    "test_pass": {"name": "So kiem tra đạt", "unit": "kiem tra",
                  "trend": "higher", "threshold": 0,
                  "nguon": "python3 patchx test"},
    "test_total": {"name": "Tong so kiem tra", "unit": "kiem tra",
                   "trend": "higher", "threshold": 0,
                   "nguon": "python3 patchx test"},
    "test_ratio": {"name": "Ty le kiem tra đạt", "unit": "%",
                   "trend": "higher", "threshold": 0.5,
                   "nguon": "test_pass / test_total"},
    "simulate_pass": {"name": "Simulate đạt", "unit": "patch",
                      "trend": "higher", "threshold": 0,
                      "nguon": "python3 patchx simulate upgraded"},
    "simulate_total": {"name": "Tong simulate", "unit": "patch",
                       "trend": "higher", "threshold": 0,
                       "nguon": "python3 patchx simulate upgraded"},
    "simulate_ratio": {"name": "Ty le simulate đạt", "unit": "%",
                       "trend": "higher", "threshold": 0.5,
                       "nguon": "simulate_pass / simulate_total"},
    "simulate_time_s": {"name": "Thoi gian simulate 60 patch", "unit": "giay",
                        "trend": "lower", "threshold": 5.0,
                        "nguon": "python3 patchx simulate upgraded (cache am)"},
    "golden_build_pass": {"name": "Golden build đạt", "unit": "bo",
                          "trend": "higher", "threshold": 0,
                          "nguon": "tests golden"},
    "golden_build_total": {"name": "Tong golden build", "unit": "bo",
                           "trend": "higher", "threshold": 0,
                           "nguon": "tests golden"},
    "scan_time_s": {"name": "Thoi gian quet APK lon", "unit": "giay",
                    "trend": "lower", "threshold": 5.0,
                    "nguon": "bench-scan (553M)"},
    "plan_time_s": {"name": "Thoi gian lap ke hoach", "unit": "giay",
                    "trend": "lower", "threshold": 5.0,
                    "nguon": "apk-plan"},
    "apply_time_s": {"name": "Thoi gian ap patch", "unit": "giay",
                     "trend": "lower", "threshold": 5.0,
                     "nguon": "apply_report.json"},
    "validate_time_s": {"name": "Thoi gian xac thuc", "unit": "giay",
                        "trend": "lower", "threshold": 30.0,
                        "nguon": "apk-debug/apk-build"},
    "build_time_s": {"name": "Thoi gian build", "unit": "giay",
                     "trend": "lower", "threshold": 60.0,
                     "nguon": "build_report.json"},
    "method_refs": {"name": "Method refs (dex cham tran)", "unit": "refs",
                    "trend": "lower", "threshold": 100,
                    "nguon": "phan tich dex"},
    "method_count": {"name": "So method (cây mau)", "unit": "method",
                     "trend": "higher", "threshold": 0,
                     "nguon": "validate tree"},
    "file_count": {"name": "So tệp (cây mau)", "unit": "tệp",
                   "trend": "higher", "threshold": 0,
                   "nguon": "validate tree"},
    "changed_files": {"name": "Tep bi sua", "unit": "tệp",
                      "trend": "lower", "threshold": 20,
                      "nguon": "apply_report.json"},
    "new_refs": {"name": "Method ref moi them", "unit": "refs",
                 "trend": "lower", "threshold": 50,
                 "nguon": "phan tich dex trước/sau"},
    "errors": {"name": "Loi", "unit": "lỗi", "trend": "lower",
               "threshold": 0, "nguon": "bao cao pipeline"},
    "warnings": {"name": "Canh bao", "unit": "canh bao", "trend": "lower",
                 "threshold": 5, "nguon": "bao cao pipeline"},
}


def load_metrics(path):
    """Nap metrics.json — tra dict rong neu chua co."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_metrics(path, metrics):
    """Ghi metrics.json (dep, tieng Viet giu nguyen)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
    return path


def capture_environment():
    """Chup moi truong chay (de so sanh cong bang khi may khac tai)."""
    try:
        load = os.getloadavg()
    except (OSError, AttributeError):
        load = []
    return {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "loadavg_1_5_15": [round(x, 2) for x in load],
        "machine": platform.machine(),
    }


def capture_metrics(overrides=None, baseline_dir=DEFAULT_BASELINE_DIR):
    """Thu thap metrics hien tai.

    - overrides: dict do nguoi dung cung cap (--set key=value hoac inputs.json).
    - Tu dong tim cac bao cao da co (apply/build/runtime) de bo sung.
    Tra dict metrics + environment.
    """
    metrics = {k: None for k in METRICS}
    if overrides:
        for k, v in overrides.items():
            if k in METRICS and v is not None:
                try:
                    metrics[k] = float(v) if isinstance(v, str) else v
                except ValueError:
                    metrics[k] = v
    # Bo sung tu bao cao da co trong kho (neu chua bi ghi de)
    _fill_from_reports(metrics, baseline_dir)
    env = capture_environment()
    env["load_note"] = ("May dung chung co the nhieu; ghi lai loadavg de "
                        "so sanh tuong doi.")
    return metrics, env


def _fill_from_reports(metrics, baseline_dir):
    """Tim cac report JSON gan nhat de dien so lieu that."""
    candidates = []
    roots = [os.path.join(BASE_DIR, "outputs", "apk"),
             os.path.join(BASE_DIR, "outputs", "pipeline"),
             os.path.join(BASE_DIR, "outputs", "bench"),
             os.path.join(BASE_DIR, "outputs", "golden")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if fn.endswith(("build_report.json", "apply_report.json",
                                "runtime_report.json", "bench_report.json",
                                "apk_build_report.json")):
                    candidates.append(os.path.join(dirpath, fn))
    for cpath in sorted(candidates, key=lambda p: os.path.getmtime(p),
                        reverse=True)[:12]:
        try:
            with open(cpath, encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        base = os.path.basename(cpath)
        if "build" in base and metrics["build_time_s"] is None:
            metrics["build_time_s"] = r.get("build_seconds")
            if metrics["method_refs"] is None:
                metrics["method_refs"] = (r.get("method_refs") or
                                          r.get("method_refs_before"))
        elif "apply" in base and metrics["apply_time_s"] is None:
            metrics["apply_time_s"] = r.get("apply_seconds")
            if metrics["changed_files"] is None:
                metrics["changed_files"] = r.get("changed_files")
            if metrics["errors"] is None:
                metrics["errors"] = (r.get("errors") or
                                     r.get("validate_total_errors"))
        elif "runtime" in base and metrics["errors"] is None:
            metrics["errors"] = r.get("errors") or (
                0 if r.get("m2") in (True, "PASS", "M2_PASS") else None)
        elif "bench" in base and metrics["scan_time_s"] is None:
            metrics["scan_time_s"] = r.get("scan_seconds") or r.get("seconds")
    # Chi so phai sinh
    if metrics["test_pass"] is not None and metrics["test_total"]:
        metrics["test_ratio"] = round(
            100.0 * metrics["test_pass"] / metrics["test_total"], 2)


def capture_full(overrides=None, baseline_dir=DEFAULT_BASELINE_DIR):
    """Chup baseline day du: test suite + simulate 60 patch + bao cao co san."""
    metrics, env = capture_metrics(overrides, baseline_dir)
    test_script = os.path.join(BASE_DIR, "tests", "run_tests.py")
    if os.path.isfile(test_script):
        try:
            proc = subprocess.run(
                [sys.executable, test_script], cwd=BASE_DIR, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
            m = re.search(r"Ket qua:\s*(\d+)/(\d+)", proc.stdout or "")
            if m:
                metrics["test_pass"] = int(m.group(1))
                metrics["test_total"] = int(m.group(2))
                metrics["test_ratio"] = round(
                    100.0 * metrics["test_pass"] / max(1, metrics["test_total"]), 2)
        except Exception:
            pass
    upgraded = os.path.join(BASE_DIR, "upgraded")
    if os.path.isdir(upgraded):
        try:
            from .simulate import run_simulation
            sim = run_simulation(upgraded)
            metrics["simulate_pass"] = sim.get("đạt")
            metrics["simulate_total"] = sim.get("tổng_patch")
            if metrics["simulate_total"]:
                metrics["simulate_ratio"] = round(
                    100.0 * metrics["simulate_pass"] / metrics["simulate_total"], 2)
            metrics["simulate_time_s"] = round(
                (sim.get("tổng_thời_gian_ms") or 0) / 1000.0, 3)
        except Exception:
            pass
    golden_gate = os.path.join(BASE_DIR, "outputs", "golden", "golden_gate.json")
    if os.path.isfile(golden_gate):
        try:
            with open(golden_gate, encoding="utf-8") as fh:
                gate = json.load(fh)
            if metrics["golden_build_pass"] is None:
                metrics["golden_build_pass"] = gate.get("golden_build_pass")
            if metrics["golden_build_total"] is None:
                metrics["golden_build_total"] = gate.get("golden_build_total")
        except (OSError, ValueError):
            pass
    return metrics, env


def compare_metrics(baseline, new, warnings=True):
    """So sanh baseline voi ket qua moi.

    Tra: items (chi tiet tung chi so) + verdict ("ACCEPT"/"BLOCK")
         + reasons (danh sach hoi quy).
    """
    items = []
    reasons = []
    for key, meta in METRICS.items():
        b = baseline.get(key)
        n = new.get(key)
        if b is None or n is None:
            continue
        b_f, n_f = float(b), float(n)
        delta = n_f - b_f
        if meta["trend"] == "higher":
            worse = delta < -meta["threshold"]
        else:
            worse = delta > meta["threshold"]
        status = "WORSE" if worse else ("BETTER" if abs(delta) > 1e-9
                                        else "OK")
        if worse:
            reasons.append("%s: %s → %s (xau hon %s %s, cho phep %s)"
                          % (key, b, n, abs(delta), meta["unit"],
                             meta["threshold"]))
        items.append({"chi_so": key, "tên": meta["name"], "baseline": b,
                      "moi": n, "don_vi": meta["unit"],
                      "xu_huong": meta["trend"], "trang_thai": status})
    verdict = "BLOCK" if reasons else "ACCEPT"
    return {"verdict": verdict, "reasons": reasons,
            "so_sanh_luc": time.strftime("%Y-%m-%d %H:%M:%S"),
            "items": items}


def render_compare(result, indent="  "):
    """In bang so sanh ra text."""
    lines = ["Ket luan: %s" % ("✅ ACCEPT" if result["verdict"] == "ACCEPT"
                               else "🚫 BLOCK (hoi quy)")]
    for it in result["items"]:
        mark = {"OK": "·", "BETTER": "↑", "WORSE": "↓"}.get(
            it["trang_thai"], "?")
        lines.append("%s%s %-18s %-8s %s → %s %s" % (
            indent, mark, it["chi_so"], it["trang_thai"],
            it["baseline"], it["moi"], it["don_vi"]))
    for r in result["reasons"]:
        lines.append("%s⚠ %s" % (indent, r))
    return "\n".join(lines)


def write_baseline(baseline_dir=DEFAULT_BASELINE_DIR, overrides=None):
    """Chup va luu baseline chuan. Tra duong dan metrics.json."""
    os.makedirs(baseline_dir, exist_ok=True)
    metrics, env = capture_metrics(overrides, baseline_dir)
    mpath = os.path.join(baseline_dir, "metrics.json")
    save_metrics(mpath, metrics)
    with open(os.path.join(baseline_dir, "environment.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(env, fh, ensure_ascii=False, indent=2)
    return mpath


def run_compare(new_path, baseline_dir=DEFAULT_BASELINE_DIR):
    """So sanh new metrics voi baseline. Tra (verdict, result)."""
    base = load_metrics(os.path.join(baseline_dir, "metrics.json"))
    new = load_metrics(new_path)
    result = compare_metrics(base, new)
    return result["verdict"], result
