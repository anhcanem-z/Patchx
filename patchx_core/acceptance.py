# -*- coding: utf-8 -*-
"""Tieu chi nghiem thu cho kien truc mức tieu + dieu kien (de xuat V2).

Chi doc fixture/APK va tra so lieu do duoc, khong ap patch:
- tai lap model (identity giu nguyen khi dung hai lần)
- tai nhan dien sau obfuscation nhe
- duong tinh gia selector o nguong READY_FOR_PREFLIGHT
- xu ly mo ho (AMBIGUOUS_TARGET phai dung)
"""

import json
import os

from .diffapk import match_app_models_v2
from .semantic_plan import SCHEMA_V2, evaluate_plan_v2, load_plan
from .smali_sem import build_app_model_v2

IDENTITY_KEYS = ("exact", "structural", "semantic")


def _load_plan(fixture_dir, spec):
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, str):
        return load_plan(os.path.join(fixture_dir, spec))
    raise ValueError("plan case phai la dict hoac tên tệp")


def _method_match(method_id, expected):
    return method_id == expected or method_id.endswith(expected)


def _reproducibility(model_a, model_b):
    b = {m["id"]: m for m in model_b.get("methods", [])}
    total = len(model_a.get("methods", []))
    same = 0
    for m in model_a.get("methods", []):
        other = b.get(m["id"])
        if other and all(m.get("identity", {}).get(k) == other.get("identity", {}).get(k)
                         for k in IDENTITY_KEYS):
            same += 1
    return {"total": total, "same": same,
            "rate": round(100.0 * same / total, 2) if total else 100.0}


def run_acceptance(fixture_dir):
    """Chay bo nghiem thu tren thu mức fixture co ``acceptance.json``."""
    manifest_path = os.path.join(fixture_dir, "acceptance.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError("thieu acceptance.json trong " + fixture_dir)
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    source = os.path.join(fixture_dir, manifest.get("source_tree", "source"))
    obfuscated = os.path.join(fixture_dir, manifest.get("obfuscated_tree", "obfuscated"))
    model_a = build_app_model_v2(source)
    model_b = build_app_model_v2(source)
    repro = _reproducibility(model_a, model_b)
    reid_rate = None
    variant_rates = {}
    if os.path.isdir(obfuscated):
        version = match_app_models_v2(model_a, build_app_model_v2(obfuscated))
        reid_rate = version["summary"]["reidentification_rate"]
        variant_rates["base"] = reid_rate
    for variant in manifest.get("obfuscation_variants", []):
        tree = os.path.join(fixture_dir, variant.get("tree", ""))
        if not os.path.isdir(tree):
            continue
        version = match_app_models_v2(model_a, build_app_model_v2(tree))
        variant_rates[variant.get("name", variant.get("tree"))] = (
            version["summary"]["reidentification_rate"])
    plan_results = []
    ready_expected, ready_wrong = 0, 0
    ambiguity_cases, ambiguity_blocked = 0, 0
    no_confident_cases, no_confident_blocked = 0, 0
    for case in manifest.get("plans", []):
        plan = _load_plan(fixture_dir, case.get("plan"))
        if plan.get("schema") != SCHEMA_V2:
            raise ValueError("acceptance chi nhan patchx.semantic-plan/v2")
        result = evaluate_plan_v2(plan, model_a)
        expected_verdict = case.get("expected_verdict")
        accepted_methods = [c["method"] for t in result.get("targets", [])
                            for c in t.get("accepted", [])]
        verdict_ok = result["verdict"] == expected_verdict
        plan_results.append({
            "name": case.get("name"), "verdict": result["verdict"],
            "expected_verdict": expected_verdict, "verdict_ok": verdict_ok,
            "accepted_methods": accepted_methods,
        })
        if expected_verdict == "READY_FOR_PREFLIGHT":
            ready_expected += 1
            expected = case.get("expected_method")
            if expected and not all(_method_match(m, expected) for m in accepted_methods):
                ready_wrong += 1
        elif expected_verdict == "AMBIGUOUS_TARGET":
            ambiguity_cases += 1
            if verdict_ok:
                ambiguity_blocked += 1
        elif expected_verdict == "NO_CONFIDENT_TARGET":
            no_confident_cases += 1
            if verdict_ok:
                no_confident_blocked += 1
    ready_ok = sum(1 for r in plan_results
                   if r["expected_verdict"] == "READY_FOR_PREFLIGHT" and r["verdict_ok"])
    metrics = {
        "ready_ok": ready_ok,
        "ready_total": ready_expected,
        "ready_rate": round(100.0 * ready_ok / ready_expected, 2) if ready_expected else None,
        "false_positive_cases": ready_wrong,
        "false_positive_rate": round(100.0 * ready_wrong / ready_expected, 2) if ready_expected else 0.0,
        "ambiguity_blocked": ambiguity_blocked,
        "ambiguity_total": ambiguity_cases,
        "ambiguity_rate": round(100.0 * ambiguity_blocked / ambiguity_cases, 2) if ambiguity_cases else None,
        "no_confident_blocked": no_confident_blocked,
        "no_confident_total": no_confident_cases,
    }
    return {
        "schema": "patchx.acceptance-report/v1",
        "fixture": os.path.abspath(fixture_dir),
        "reproducibility": repro,
        "reidentification_rate": reid_rate,
        "reidentification_variants": variant_rates,
        "plans": plan_results,
        "metrics": metrics,
    }
