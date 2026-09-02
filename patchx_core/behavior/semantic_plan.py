# -*- coding: utf-8 -*-
"""Ke hoach thay doi theo mức tieu + dieu kien (Dot B).

Dinh dang nay la lop ke hoach an toan nam trước patch.txt/Engine: no chi tim,
cham điểm va xac minh ung vien. Khong ham nao trong mo-dun nay ghi vao cây APK
hay goi Engine.apply; moi thay doi van can nguoi dung duyet va qua preflight.
"""

import json


SCHEMA = "patchx.semantic-plan/v1"
SCHEMA_V2 = "patchx.semantic-plan/v2"
ALLOWED_OPERATIONS = {"RETURN_CONSTANT", "INSERT_HOOK", "REPLACE_FROM_REFERENCE",
                      "SET_FIELD", "TRACE"}
REQUIRED_VERIFY = {"preflight", "validate", "build", "runtime"}


def load_plan(path):
    """Nap va kiem tra cau truc co ban cua ke hoach JSON."""
    with open(path, encoding="utf-8") as fh:
        plan = json.load(fh)
    errors = validate_plan_v2(plan) if plan.get("schema") == SCHEMA_V2 else validate_plan(plan)
    if errors:
        raise ValueError("Ke hoach khong hop le: " + "; ".join(errors))
    return plan


def validate_plan(plan):
    """Tra danh sach lỗi; co tinh chat de plan khong thanh patch an."""
    errors = []
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        return ["schema phai la %s" % SCHEMA]
    if not str(plan.get("goal", "")).strip():
        errors.append("thieu goal")
    targets = plan.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("can it nhat mot target")
    for i, target in enumerate(targets or []):
        if not isinstance(target, dict) or not isinstance(target.get("conditions"), dict):
            errors.append("target %d thieu conditions" % (i + 1))
    for op in plan.get("operations", []):
        if not isinstance(op, dict) or op.get("type") not in ALLOWED_OPERATIONS:
            errors.append("operation khong duoc ho tro: %r" % op)
    verify = set(plan.get("verification", []))
    unknown = verify - REQUIRED_VERIFY
    if unknown:
        errors.append("verification khong hop le: %s" % ", ".join(sorted(unknown)))
    return errors


def _validate_intent(intent):
    """Khong cho operation_intent tro thanh patch Smali an trong plan V2."""
    if not isinstance(intent, dict) or intent.get("type") not in ALLOWED_OPERATIONS:
        return "operation_intent khong duoc ho tro: %r" % intent
    forbidden = {"body", "smali", "content", "match", "replace", "target_file"}
    present = forbidden & set(intent)
    if present:
        return "operation_intent chua noi dung thuc thi bi cam: %s" % ", ".join(sorted(present))
    if not isinstance(intent.get("target", ""), str) or not intent.get("target", "").strip():
        return "operation_intent can target la tên target logic"
    return ""


def validate_plan_v2(plan):
    """Kiem tra chat schema V2; V2 chi mo ta y dinh va chinh sach chon target."""
    errors = []
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA_V2:
        return ["schema phai la %s" % SCHEMA_V2]
    if not str(plan.get("goal", "")).strip():
        errors.append("thieu goal")
    targets = plan.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("can it nhat mot target")
    names = set()
    for i, target in enumerate(targets or []):
        where = "target %d" % (i + 1)
        if not isinstance(target, dict):
            errors.append(where + " phai la object")
            continue
        name = target.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(where + " thieu name")
        elif name in names:
            errors.append(where + " trung name: " + name)
        else:
            names.add(name)
        selector = target.get("selector")
        if not isinstance(selector, dict) or not isinstance(selector.get("all"), list) or not selector["all"]:
            errors.append(where + " can selector.all khong rong")
        else:
            for atom in selector["all"]:
                if not isinstance(atom, dict) or len(atom) != 1:
                    errors.append(where + " selector.all chi nhan object mot dieu kien")
                    continue
                key, value = next(iter(atom.items()))
                if key not in {"return_type", "parameters", "min_branch_count",
                               "requires_call", "requires_caller",
                               "requires_string", "requires_field_read",
                               "requires_field_write"}:
                    errors.append(where + " dieu kien khong ho tro: " + str(key))
                elif key == "parameters" and not isinstance(value, list):
                    errors.append(where + " parameters phai la list")
                elif key == "min_branch_count" and (not isinstance(value, int) or value < 0):
                    errors.append(where + " min_branch_count phai la so nguyen khong am")
                elif key.startswith("requires_") and not isinstance(value, str):
                    errors.append(where + " " + key + " phai la chuoi")
        near = (selector or {}).get("near_entry") if isinstance(selector, dict) else None
        if near is not None and (not isinstance(near, dict)
                                 or not isinstance(near.get("max_distance"), int)
                                 or near["max_distance"] < 0):
            errors.append(where + " near_entry.max_distance phai la so nguyen khong am")
        policy = target.get("policy")
        if not isinstance(policy, dict):
            errors.append(where + " thieu policy")
        else:
            score = policy.get("min_score")
            maximum = policy.get("max_accepted")
            if not isinstance(score, (int, float)) or not 0 <= score <= 100:
                errors.append(where + " policy.min_score phai trong 0..100")
            # V2 khong tu chon trong tap nhieu ung vien.  Hop dong cua
            # READY_FOR_PREFLIGHT la duy nhat mot mức tieu cho moi target;
            # plan-compile cung dua vao bat bien nay de khong phai phat hien
            # muon mot plan khong the tao draft.
            if maximum != 1:
                errors.append(where + " policy.max_accepted phải bằng 1 (nhiều ứng viên luôn STOP)")
            if policy.get("on_ambiguous") != "STOP":
                errors.append(where + " policy.on_ambiguous phai la STOP")
    intents = plan.get("operation_intent")
    if not isinstance(intents, list) or not intents:
        errors.append("can it nhat mot operation_intent")
    else:
        for intent in intents:
            err = _validate_intent(intent)
            if err:
                errors.append(err)
            elif intent["target"] not in names:
                errors.append("operation_intent target khong ton tai: " + intent["target"])
    verify = set(plan.get("verification", []))
    if verify != REQUIRED_VERIFY:
        errors.append("verification V2 phai du: " + ", ".join(sorted(REQUIRED_VERIFY)))
    return errors


def _matches(method, conditions):
    """So khớp bao thu mot method voi dieu kien cau truc/ngu nghia."""
    evidence, missing = [], []
    checks = (
        ("return_type", method.get("return_type")),
        ("fingerprint", method.get("fingerprint")),
    )
    for key, actual in checks:
        wanted = conditions.get(key)
        if wanted is None:
            continue
        if actual == wanted:
            evidence.append(key)
        else:
            missing.append(key)
    if "parameters" in conditions:
        if method.get("parameters") == conditions["parameters"]:
            evidence.append("parameters")
        else:
            missing.append("parameters")
    if "min_branch_count" in conditions:
        if method.get("branch_count", 0) >= int(conditions["min_branch_count"]):
            evidence.append("min_branch_count")
        else:
            missing.append("min_branch_count")
    for key, values in (("requires_calls", method.get("calls", [])),
                        ("requires_field_reads", method.get("field_reads", [])),
                        ("requires_strings", method.get("strings", []))):
        required = conditions.get(key, [])
        for item in required:
            if item in values:
                evidence.append(key + ":" + item)
            else:
                missing.append(key + ":" + item)
    total = len(evidence) + len(missing)
    score = round((len(evidence) / total * 100) if total else 0.0, 1)
    return score, evidence, missing


def evaluate_plan(plan, model):
    """Tim ung vien theo plan trong app-model va tra bang chung day du."""
    errors = validate_plan(plan)
    if errors:
        raise ValueError("Ke hoach khong hop le: " + "; ".join(errors))
    results = []
    for target in plan["targets"]:
        candidates = []
        for method in model.get("methods", []):
            score, evidence, missing = _matches(method, target["conditions"])
            if evidence:
                candidates.append({"method": method["id"], "file": method["file"],
                                   "line": method["line"], "score": score,
                                   "evidence": evidence, "missing": missing,
                                   "fingerprint": method["fingerprint"]})
        candidates.sort(key=lambda x: (-x["score"], x["method"]))
        min_score = float(target.get("min_score", 70))
        accepted = [x for x in candidates if x["score"] >= min_score]
        rejected = [x for x in candidates if x["score"] < min_score]
        results.append({"name": target.get("name", "target"), "min_score": min_score,
                        "candidates": candidates, "accepted": accepted,
                        "rejected": rejected})
    ok = all(item["accepted"] for item in results)
    return {"schema": SCHEMA, "goal": plan["goal"], "verdict":
            "READY_FOR_PREFLIGHT" if ok else "NO_CONFIDENT_TARGET",
            "targets": results, "operations": plan.get("operations", []),
            "verification": plan.get("verification", [])}


def _matches_v2(method, selector):
    """Cham tung atom selector tren model V2 va luon tra evidence am/duong."""
    features = method.get("features", {})
    relations = method.get("relations", {})
    evidence, missing = [], []
    for atom in selector.get("all", []):
        key, wanted = next(iter(atom.items()))
        actual = {
            "return_type": features.get("return_type"),
            "parameters": features.get("parameters"),
            "min_branch_count": features.get("branch_count", 0),
            "requires_call": features.get("calls", []),
            "requires_caller": relations.get("callers", []),
            "requires_string": features.get("strings", []),
            "requires_field_read": features.get("field_reads", []),
            "requires_field_write": features.get("field_writes", []),
        }[key]
        ok = actual >= wanted if key == "min_branch_count" else wanted in actual if key.startswith("requires_") else actual == wanted
        (evidence if ok else missing).append(key + (":" + str(wanted) if key.startswith("requires_") else ""))
    near = selector.get("near_entry")
    if near is not None:
        distance = relations.get("entry_distance")
        ok = distance is not None and distance <= near["max_distance"]
        (evidence if ok else missing).append("near_entry<=%d" % near["max_distance"])
    total = len(evidence) + len(missing)
    return round(100 * len(evidence) / total, 1) if total else 0.0, evidence, missing


def evaluate_plan_v2(plan, model):
    """Danh gia plan V2, chan ambiguity va khong goi code thuc thi."""
    errors = validate_plan_v2(plan)
    if errors:
        raise ValueError("Ke hoach khong hop le: " + "; ".join(errors))
    if model.get("schema") != "patchx.app-model/v2":
        return {"schema": SCHEMA_V2, "goal": plan["goal"],
                "verdict": "INSUFFICIENT_EVIDENCE", "reason":
                "semantic-plan/v2 can patchx.app-model/v2", "targets": [],
                "operation_intent": plan["operation_intent"],
                "verification": plan["verification"]}
    results, any_ambiguous = [], False
    for target in plan["targets"]:
        candidates = []
        for method in model.get("methods", []):
            score, evidence, missing = _matches_v2(method, target["selector"])
            candidates.append({"method": method["id"], "file": method["file"],
                               "line": method["line"], "score": score,
                               "evidence": evidence, "missing": missing,
                               "identity": method.get("identity", {}),
                               "entry_distance": method.get("relations", {}).get("entry_distance")})
        candidates.sort(key=lambda x: (-x["score"], x["method"]))
        policy = target["policy"]
        accepted = [x for x in candidates if x["score"] >= policy["min_score"]]
        rejected = [x for x in candidates if x["score"] < policy["min_score"]]
        ambiguous = len(accepted) > policy["max_accepted"]
        any_ambiguous = any_ambiguous or ambiguous
        results.append({"name": target["name"], "policy": policy,
                        "candidates": candidates, "accepted": accepted,
                        "rejected": rejected,
                        "ambiguous": ambiguous})
    if any_ambiguous:
        verdict = "AMBIGUOUS_TARGET"
    elif all(item["accepted"] for item in results):
        verdict = "READY_FOR_PREFLIGHT"
    else:
        verdict = "NO_CONFIDENT_TARGET"
    return {"schema": SCHEMA_V2, "goal": plan["goal"], "verdict": verdict,
            "targets": results, "operation_intent": plan["operation_intent"],
            "verification": plan["verification"]}


def suggest_selector_fix(plan, result):
    """Goi y siet/noi selector tu ket qua danh gia (vong hoc tu that bai).

    Khong tu sua plan. Tra danh sach goi y de nguoi dung chon; moi thay doi
    van phai chay lai ``semantic-plan`` va qua preflight.
    """
    tips = []
    for idx, target in enumerate(plan.get("targets", [])):
        item = result.get("targets", [])[idx] if idx < len(result.get("targets", [])) else {}
        if item.get("ambiguous"):
            tips.append({"target": target.get("name"), "kind": "ambiguous",
                         "advice": [
                             "Tang policy.min_score hoac giam policy.max_accepted.",
                             "Them requires_caller/requires_call/requires_string "
                             "de tach ung vien trung điểm.",
                             "Siet near_entry.max_distance ve dung khoang cach mức tieu."]})
        elif item.get("accepted"):
            continue
        else:
            missing = {}
            rejected = item.get("rejected", [])
            for cand in rejected:
                for atom in cand.get("missing", []):
                    missing[atom] = missing.get(atom, 0) + 1
            common = [atom for atom, count in sorted(missing.items())
                      if rejected and count == len(rejected)]
            tips.append({"target": target.get("name"), "kind": "no_confident",
                         "common_missing": common,
                         "advice": [
                             "Kiem tra selector.all: cac atom chung bi thieu co the qua chat.",
                             "Dung version-map/knowledge suggest-plan de tim ung vien tuong dong.",
                             "Noi tung atom mot va chay lai; khong gop nhieu thay doi cung luc."]})
    return tips


def plan_from_model_diff(original_model, modified_model, goal="Thay doi rut ra tu APK mau"):
    """Rut ke hoach tham chieu tu hai app-model, khong sinh patch thuc thi.

    Method co cung dinh danh nhung fingerprint doi duoc ghi thanh target voi
    fingerprint cua ban goc; operation chi la REPLACE_FROM_REFERENCE de nguoi
    dung duyet/chuyen doi thanh patch tuong thich o buoc sau.
    """
    before = {m["id"]: m for m in original_model.get("methods", [])}
    after = {m["id"]: m for m in modified_model.get("methods", [])}
    targets = []
    for mid in sorted(set(before) & set(after)):
        a, b = before[mid], after[mid]
        if a["fingerprint"] == b["fingerprint"]:
            continue
        conditions = {"return_type": a["return_type"],
                      "parameters": a["parameters"],
                      "fingerprint": a["fingerprint"]}
        targets.append({"name": "target_%d" % (len(targets) + 1),
                        "conditions": conditions, "min_score": 100,
                        "reference": {"original": mid, "modified": mid,
                                      "modified_fingerprint": b["fingerprint"]}})
    return {"schema": SCHEMA, "goal": goal, "targets": targets,
            "operations": ([{"type": "REPLACE_FROM_REFERENCE",
                             "note": "Chi tham chieu APK mau; can nguoi dung duyet"}]
                           if targets else []),
            "verification": ["preflight", "validate", "build", "runtime"]}


def plan_v2_from_version_map(version_map, original_model, modified_model,
                             goal="Ke hoach tham chieu tu ban do phien ban"):
    """Sinh semantic-plan/V2 chi-doc tu cac ghep method *duy nhat*.

    Ham nay khong suy dien thao tac thay doi va khong goi engine. Moi target
    chi mang selector lay tu model goc cung evidence cua ghep version-map;
    khi danh gia tren APK khac, policy ``max_accepted=1`` van bat buoc dung
    neu selector tro nen mo ho.
    """
    if version_map.get("schema") != "patchx.version-match/v1":
        raise ValueError("can patchx.version-match/v1")
    if original_model.get("schema") != "patchx.app-model/v2" or \
            modified_model.get("schema") != "patchx.app-model/v2":
        raise ValueError("can hai patchx.app-model/v2")
    before = {m["id"]: m for m in original_model.get("methods", [])}
    after = {m["id"]: m for m in modified_model.get("methods", [])}
    targets, intents = [], []
    for row in version_map.get("matches", []):
        if row.get("status") not in {"exact", "structural", "semantic"}:
            continue
        source, destination = before.get(row.get("before")), after.get(row.get("after"))
        if not source or not destination:
            continue
        f = source.get("features", {})
        selector = {"all": [
            {"return_type": f.get("return_type", "V")},
            {"parameters": f.get("parameters", [])},
            {"min_branch_count": f.get("branch_count", 0)},
        ]}
        calls = f.get("calls", [])
        if calls:
            selector["all"].append({"requires_call": calls[0]})
        distance = source.get("relations", {}).get("entry_distance")
        if distance is not None:
            selector["near_entry"] = {"max_distance": distance}
        name = "version_target_%d" % (len(targets) + 1)
        targets.append({
            "name": name, "selector": selector,
            "policy": {"min_score": 100, "max_accepted": 1,
                       "on_ambiguous": "STOP"},
            "reference": {
                "source_method": source["id"], "target_method": destination["id"],
                "match_level": row["status"],
                "identity_matches": row.get("identity_matches", []),
                "source_identity": source.get("identity", {}),
                "target_identity": destination.get("identity", {}),
                "source_evidence": source.get("evidence", {}),
                "target_evidence": destination.get("evidence", {}),
            },
        })
        intents.append({"type": "TRACE", "target": name,
                        "note": "Chi tham chieu version-map; can nguoi dung duyet."})
    return {"schema": SCHEMA_V2, "goal": goal, "targets": targets,
            "operation_intent": intents,
            "verification": ["preflight", "validate", "build", "runtime"],
            "provenance": {"source": "patchx.version-match/v1",
                           "recommendation_only": True}}
