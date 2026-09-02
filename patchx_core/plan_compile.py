# -*- coding: utf-8 -*-
"""Bien dich semantic-plan/V2 thanh transaction *nhap*, khong thuc thi."""

import hashlib
import os

from .semantic_plan import SCHEMA_V2, evaluate_plan_v2, validate_plan_v2


def tree_evidence_hash(tree):
    """Hash noi dung co thu tu cua manifest + Smali, dung khoa evidence."""
    digest = hashlib.sha256()
    paths = []
    for root, dirs, files in os.walk(tree):
        dirs[:] = sorted(d for d in dirs if d not in {"build", "original", ".patchx"})
        for name in sorted(files):
            if name.endswith(".smali") or name == "AndroidManifest.xml":
                paths.append(os.path.join(root, name))
    for path in sorted(paths):
        rel = os.path.relpath(path, tree).replace(os.sep, "/")
        digest.update(rel.encode("utf-8") + b"\0")
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            digest.update(b"<unreadable>")
    return "sha256:" + digest.hexdigest()


def compile_plan_v2(plan, model, tree):
    """Tao draft bat bien; khong chua Smali, patch hay lệnh thuc thi.

    Chi compile khi selector tra dung mot ung vien cho tung target. Hash cây
    la dieu kien bat buoc o preflight cua buoc thuc thi tuong lai.
    """
    if validate_plan_v2(plan):
        raise ValueError("semantic-plan/V2 khong hop le")
    if model.get("schema") != "patchx.app-model/v2":
        raise ValueError("plan-compile can patchx.app-model/v2")
    verdict = evaluate_plan_v2(plan, model)
    if verdict["verdict"] != "READY_FOR_PREFLIGHT":
        raise ValueError("plan-compile bi chan: " + verdict["verdict"])
    selected = []
    for target in verdict["targets"]:
        accepted = target["accepted"]
        if len(accepted) != 1:
            raise ValueError("plan-compile can dung mot ung vien: " + target["name"])
        item = accepted[0]
        selected.append({"target": target["name"], "method": item["method"],
                         "file": item["file"], "line": item["line"],
                         "identity": item.get("identity", {}),
                         "evidence": item["evidence"]})
    return {"schema": "patchx.transaction-draft/v1", "goal": plan["goal"],
            "status": "DRAFT_REQUIRES_APPROVAL",
            "tree": os.path.abspath(tree),
            "tree_evidence_hash": tree_evidence_hash(tree),
            "plan_schema": SCHEMA_V2,
            "plan": plan,
            "selected_targets": selected,
            "operation_intent": plan["operation_intent"],
            "required_gates": ["approval", "preflight", "validate", "build", "runtime"],
            "executable": False}


def verify_draft_evidence(draft, tree):
    """Gate chi-doc: chan draft neu hash cây khac luc compile."""
    if draft.get("schema") != "patchx.transaction-draft/v1":
        return {"status": "BLOCKED", "reason": "schema draft khong hop le"}
    if draft.get("status") != "DRAFT_REQUIRES_APPROVAL" or draft.get("executable"):
        return {"status": "BLOCKED", "reason": "draft khong an toan"}
    actual = tree_evidence_hash(tree)
    expected = draft.get("tree_evidence_hash", "")
    return {"status": "READY_FOR_APPROVAL" if actual == expected else "BLOCKED",
            "expected_hash": expected, "actual_hash": actual,
            "reason": "evidence khớp" if actual == expected else "cây APK da thay doi"}


def revalidate_draft(draft, tree):
    """Khi hash cây thay doi, danh gia lai plan V2 tren cây moi.

    Khong tu ap: chi sinh draft moi khi verdict van ``READY_FOR_PREFLIGHT``;
    neu mo ho/khong du bang chung thi tra BLOCKED va yeu cau nguoi dung siet
    selector.
    """
    report = verify_draft_evidence(draft, tree)
    if report["status"] != "BLOCKED" or report.get("reason") != "cây APK da thay doi":
        return {"status": report["status"], "reason": report["reason"],
                "recompiled": False}
    plan = draft.get("plan")
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA_V2:
        return {"status": "BLOCKED", "reason":
                "draft khong mang semantic-plan/V2 de danh gia lai",
                "recompiled": False}
    from .smali_sem import build_app_model_v2
    model = build_app_model_v2(tree)
    verdict = evaluate_plan_v2(plan, model)
    if verdict["verdict"] != "READY_FOR_PREFLIGHT":
        return {"status": "BLOCKED",
                "reason": "danh gia lai plan tren cây moi: " + verdict["verdict"],
                "verdict": verdict["verdict"], "recompiled": False}
    new_draft = compile_plan_v2(plan, model, tree)
    return {"status": "READY_FOR_APPROVAL",
            "reason": "da danh gia lai plan va khoa evidence moi",
            "recompiled": True, "draft": new_draft}
