# -*- coding: utf-8 -*-
"""Ban do flag dieu khien hanh vi tu xa (Tang 2).

Quet cây APK da giai ma de lap ban do: field boolean (hoac AtomicBoolean)
duoc doc/ghi o dau, class nao dang giu chung — tu do sinh patch ep gia tri
tai moi điểm READ (điểm sau lop giai ma → bat chap payload ma hoa).
"""

import json
import os
import re
import zipfile

_FIELD_DECL = re.compile(
    r"^\.field\s+(?P<mods>[A-Za-z0-9_ ]*?)\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*):"
    r"(?P<type>\S+)\s*$")
_READ = re.compile(
    r"\b(?:sget|iget)-boolean\s+([vp]\d+)(?:,\s*[vp]\d+)?,\s*"
    r"(?P<field>L[^;]+;->[A-Za-z0-9_$]+:Z)\b")
_WRITE = re.compile(
    r"\b(?:sput|iput)-boolean\s+([vp]\d+)(?:,\s*[vp]\d+)?,\s*"
    r"(?P<field>L[^;]+;->[A-Za-z0-9_$]+:Z)\b")
_ATOMIC_CALL = re.compile(
    r"\b(?:invoke-virtual|invoke-static)\s*\{[^}]*\},\s*"
    r"(?P<field>L[^;]+;->[A-Za-z0-9_$]+:Ljava/util/concurrent/atomic/"
    r"AtomicBoolean;)->(?P<op>get\(\)Z|set\(Z\)V)\b")
_CLASS_HEAD = re.compile(r"^\.class\s+[^ ]*\s+(?P<cls>L[^;]+;)\s*$")
_METHOD_HEAD = re.compile(r"^\.method\s+(?P<sig>.*)$")
_SINK_CALL = re.compile(
    r"^(?:Landroid/net/|Ljavax/net/|Ljava/net/|Lokhttp3?/|"
    r"Lretrofit2/|Lorg/apache/http/|Lkotlinx/coroutines/)")
_TRANSFORM_CALL = re.compile(
    r"^(?:Ljava/security/|Ljavax/crypto/|Landroid/util/Base64;|"
    r"Ljava/util/zip/|Lorg/json/|Lcom/google/gson/|Ljava/lang/StringBuilder;|"
    r"Lkotlin/text/)")


def _iter_smali(tree_root):
    for root, _dirs, files in os.walk(tree_root):
        if ".patchx" in root.split(os.sep):
            continue
        for f in files:
            if f.endswith(".smali"):
                yield os.path.join(root, f)


def build_remote_map(tree_root, with_atomic=True):
    """Quet cây APK, tra dict ban do flag (dung json.dumps truc tiep duoc)."""
    tree_root = os.path.abspath(tree_root)
    flags = {}
    scanned = 0
    for path in _iter_smali(tree_root):
        rel = os.path.relpath(path, tree_root)
        scanned += 1
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        cls = ""
        method = ""
        for lineno, raw in enumerate(lines, 1):
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(".class "):
                m = _CLASS_HEAD.match(stripped)
                cls = m.group(1) if m else ""
                method = ""
                continue
            if stripped.startswith(".method "):
                m = _METHOD_HEAD.match(stripped)
                method = m.group(1).strip() if m else ""
                continue
            if stripped.startswith(".end method"):
                method = ""
                continue
            if stripped.startswith(".field "):
                m = _FIELD_DECL.match(stripped)
                if not m:
                    continue
                name, ftype = m.group("name"), m.group("type")
                if ftype == "Z":
                    fkey = "%s->%s:Z" % (cls, name)
                    is_static = "static" in m.group("mods").split()
                    flags.setdefault(fkey, {
                        "class": cls, "name": name, "type":
                        "static" if is_static else "instance",
                        "atomic": False, "reads": [], "writes": [],
                    })
                elif with_atomic and ftype == \
                        "Ljava/util/concurrent/atomic/AtomicBoolean;":
                    fkey = "%s->%s:AtomicBoolean" % (cls, name)
                    flags.setdefault(fkey, {
                        "class": cls, "name": name, "type":
                        "static" if "static" in m.group("mods").split()
                        else "instance",
                        "atomic": True, "reads": [], "writes": [],
                    })
                continue
            for rx, kind in ((_READ, "reads"), (_WRITE, "writes")):
                for m in rx.finditer(line):
                    fkey = m.group("field")
                    entry = flags.setdefault(fkey, {
                        "class": m.group("field").split(";->")[0] + ";",
                        "name": m.group("field").split(";->")[1][:-2],
                        "type": "static" if stripped.startswith("sget") or
                        stripped.startswith("sput") else "instance",
                        "atomic": False, "reads": [], "writes": [],
                    })
                    entry[kind].append(
                        {"file": rel, "method": method, "line": lineno})
            if with_atomic:
                for m in _ATOMIC_CALL.finditer(line):
                    fkey = m.group("field")
                    entry = flags.setdefault(fkey, {
                        "class": m.group("field").split(";->")[0] + ";",
                        "name": m.group("field").split(";->")[1][:-2],
                        "type": "static", "atomic": True,
                        "reads": [], "writes": [],
                    })
                    entry["reads" if m.group("op").startswith("get")
                          else "writes"].append(
                        {"file": rel, "method": method, "line": lineno})
    out = {
        "tree": tree_root,
        "scanned_files": scanned,
        "flags": flags,
    }
    return out


def write_remote_map(tree_root, out_path, with_atomic=True):
    data = build_remote_map(tree_root, with_atomic=with_atomic)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return data


def build_force_patch(remote_map, overrides, out_zip, title="Ep flag tu xa"):
    """Sinh patch zip ep gia tri boolean tai moi điểm READ cua cac flag liet ke.

    overrides: { "Lcls;->fld:Z": true|false } — phai co trong remote_map
    (hoac dang AtomicBoolean: "Lcls;->fld:AtomicBoolean": true).
    """
    flags = remote_map.get("flags", {})
    lines = [
        "# %s — sinh tu dong tu remote_flags.json" % title,
        "",
        "[MIN_ENGINE_VER]",
        "2",
        "[/MIN_ENGINE_VER]",
        "",
        "[AUTHOR]",
        "Patchx Remote Control",
        "[/AUTHOR]",
        "",
        "[PACKAGE]",
        "*",
        "[/PACKAGE]",
        "",
        "[REMOTE_CONFIG]",
        "CONFIG_URL:",
        "https://patchx.local/remote-data-control.json",
        "TARGET:",
        "[LAUNCHER_ACTIVITIES]",
        "METHOD:",
        "onCreate",
        "FORCE:",
    ]
    used = []
    for field, val in overrides.items():
        fkey = field
        if fkey not in flags:
            if fkey.endswith(":Z"):
                alt = fkey[:-2] + "AtomicBoolean"
            else:
                alt = fkey[:-14] + "Z" if fkey.endswith("AtomicBoolean") \
                    else None
            if alt and alt in flags:
                fkey = alt
        if fkey not in flags:
            raise ValueError("Flag khong co trong ban do: %s" % field)
        want = "true" if val else "false"
        if fkey.endswith("AtomicBoolean"):
            # AtomicBoolean khong ep duoc bang FORCE truc tiep; ghi chu.
            continue
        lines.append("%s = %s" % (fkey, want))
        used.append((fkey, want))
    lines.append("[/REMOTE_CONFIG]")
    if not used:
        raise ValueError("Khong co flag :Z nao de ep (AtomicBoolean can Tang 3)")
    text = "\n".join(lines) + "\n"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("patch.txt", text)
    return text


def summary_text(remote_map):
    flags = remote_map.get("flags", {})
    total_reads = sum(len(f["reads"]) for f in flags.values())
    total_writes = sum(len(f["writes"]) for f in flags.values())
    n_atomic = sum(1 for f in flags.values() if f["atomic"])
    return (
        "Cay: %s\nSo file smali da quet: %d\n"
        "Flag boolean: %d (%d AtomicBoolean)\n"
        "Diem doc: %d | Diem ghi: %d\n"
        % (remote_map.get("tree", ""), remote_map.get("scanned_files", 0),
           len(flags), n_atomic, total_reads, total_writes))


def build_decision_flow(tree):
    """Dung ban do luong quyet dinh/du lieu tu ``patchx.app-model/v2``.

    Chi doc cây APK, khong sua gi. Moi method duoc phan loại thanh
    ``source``/``transform``/``decision``/``sink``; canh lay tu call-graph V2.
    Tu moi điểm quyet dinh, BFS theo callee tim duong toi sink (toi da 3 buoc).
    """
    from .smali_sem import build_app_model_v2
    model = build_app_model_v2(tree)
    methods = model["methods"]
    by_id = {m["id"]: m for m in methods}
    nodes = []
    for m in methods:
        calls = m["features"].get("calls", [])
        is_sink = any(_SINK_CALL.match(c) for c in calls)
        is_decision = (m["features"].get("return_type") == "Z"
                       or m["features"].get("branch_count", 0) > 0)
        is_source = (m["relations"].get("entry_distance") == 0
                     or m["features"].get("strings")
                     or m["features"].get("field_reads"))
        node_type = ("decision" if is_decision else
                     "sink" if is_sink else
                     "source" if is_source else "transform")
        nodes.append({
            "id": m["id"], "class": m["class"], "file": m["file"],
            "line": m["line"], "type": node_type,
            "return_type": m["features"].get("return_type"),
            "entry_distance": m["relations"].get("entry_distance"),
            "branch_count": m["features"].get("branch_count", 0),
            "string_count": len(m["features"].get("strings", [])),
            "call_count": len(calls),
        })
    ids = set(by_id)
    edges = [e for e in model.get("call_edges", [])
             if e["from"] in ids and e["to"] in ids]
    decision_paths = []
    for node in nodes:
        if node["type"] != "decision":
            continue
        seen = {node["id"]}
        frontier = [node["id"]]
        sinks = []
        for _depth in range(3):
            nxt = []
            for method_id in frontier:
                for target in by_id.get(method_id, {}).get("relations", {}).get("callees", []):
                    if target in seen or target not in by_id:
                        continue
                    seen.add(target)
                    nxt.append(target)
                    if _SINK_CALL.match(target):
                        sinks.append(target)
            frontier = nxt
            if sinks:
                break
        if sinks:
            decision_paths.append({"decision": node["id"],
                                   "reachable_sinks": sorted(set(sinks))})
    by_type = {}
    for n in nodes:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    return {"schema": "patchx.decision-flow/v1",
            "tree": os.path.abspath(tree),
            "nodes": nodes, "edges": edges,
            "decision_paths": decision_paths,
            "summary": {"methods": len(nodes), "edges": len(edges),
                        "nodes_by_type": by_type,
                        "decisions_with_sinks": len(decision_paths)}}


def flow_summary_text(flow):
    s = flow["summary"]
    by_type = ", ".join("%s=%d" % (k, v)
                        for k, v in sorted(s.get("nodes_by_type", {}).items()))
    return ("Cay: %s\nLuồng quyết định/dữ liệu: %d method, %d canh goi\n"
            "Phân loại: %s\nĐiểm quyết định có đường tới sink: %d\n"
            % (flow.get("tree", ""), s.get("methods", 0), s.get("edges", 0),
               by_type or "—", s.get("decisions_with_sinks", 0)))


def build_data_flow(tree):
    """Dung ban do luong du lieu co kieu du lieu va do tin cây (V2 mo rong).

    Moi method co the mang nhieu role; ``primary_role`` chon vai tro manh nhat
    theo thu tu ``decision > sink > transform > source > transform``. Canh van
    lay tu call-graph V2, kem duong tu decision toi sink.
    """
    from .smali_sem import build_app_model_v2
    model = build_app_model_v2(tree)
    methods = model["methods"]
    by_id = {m["id"]: m for m in methods}
    nodes = []
    for m in methods:
        calls = m["features"].get("calls", [])
        reads = m["features"].get("field_reads", [])
        strings = m["features"].get("strings", [])
        roles = []
        if m["features"].get("return_type") == "Z" or m["features"].get("branch_count", 0) > 0:
            roles.append("decision")
        if any(_SINK_CALL.match(c) for c in calls):
            roles.append("sink")
        if any(_TRANSFORM_CALL.match(c) for c in calls):
            roles.append("transform")
        if m["relations"].get("entry_distance") == 0 or strings or reads:
            roles.append("source")
        if not roles:
            roles.append("transform")
        priority = ("decision", "sink", "transform", "source")
        primary = next((r for r in priority if r in roles), roles[0])
        data_type = "unknown"
        if "decision" in roles and m["features"].get("return_type") == "Z":
            data_type = "boolean"
        elif any(c.startswith(("Ljava/security/", "Ljavax/crypto/",
                               "Landroid/util/Base64;", "Ljava/util/zip/")) for c in calls):
            data_type = "bytes"
        elif strings or any("JSON" in c or "Gson" in c for c in calls):
            data_type = "string"
        elif any("Landroid/net/" in c or "Ljavax/net/" in c or "Ljava/net/" in c for c in calls):
            data_type = "network"
        confidence = {"source": 0.9, "decision": 0.9, "transform": 0.7,
                      "sink": 0.6}.get(primary, 0.5)
        nodes.append({
            "id": m["id"], "class": m["class"], "file": m["file"],
            "line": m["line"], "primary_role": primary, "roles": roles,
            "data_type": data_type, "confidence": confidence,
            "entry_distance": m["relations"].get("entry_distance"),
            "branch_count": m["features"].get("branch_count", 0),
            "string_count": len(strings), "call_count": len(calls),
        })
    ids = set(by_id)
    edges = [e for e in model.get("call_edges", [])
             if e["from"] in ids and e["to"] in ids]
    decision_paths = []
    for node in nodes:
        if node["primary_role"] != "decision":
            continue
        seen = {node["id"]}
        frontier = [node["id"]]
        sinks = []
        for _depth in range(3):
            nxt = []
            for method_id in frontier:
                for target in by_id.get(method_id, {}).get("relations", {}).get("callees", []):
                    if target in seen or target not in by_id:
                        continue
                    seen.add(target)
                    nxt.append(target)
                    if _SINK_CALL.match(target):
                        sinks.append(target)
            frontier = nxt
            if sinks:
                break
        if sinks:
            decision_paths.append({"decision": node["id"],
                                   "reachable_sinks": sorted(set(sinks))})
    by_role = {}
    by_type = {}
    for n in nodes:
        by_role[n["primary_role"]] = by_role.get(n["primary_role"], 0) + 1
        by_type[n["data_type"]] = by_type.get(n["data_type"], 0) + 1
    return {"schema": "patchx.data-flow/v1",
            "tree": os.path.abspath(tree),
            "nodes": nodes, "edges": edges,
            "decision_paths": decision_paths,
            "summary": {"methods": len(nodes), "edges": len(edges),
                        "nodes_by_role": by_role, "data_types": by_type,
                        "decisions_with_sinks": len(decision_paths)}}


def dataflow_summary_text(flow):
    s = flow["summary"]
    roles = ", ".join("%s=%d" % (k, v)
                      for k, v in sorted(s.get("nodes_by_role", {}).items()))
    types = ", ".join("%s=%d" % (k, v)
                      for k, v in sorted(s.get("data_types", {}).items()))
    return ("Cay: %s\nData-flow: %d method, %d canh goi\n"
            "Vai trò: %s\nKiểu dữ liệu: %s\nĐiểm quyết định tới sink: %d\n"
            % (flow.get("tree", ""), s.get("methods", 0), s.get("edges", 0),
               roles or "—", types or "—", s.get("decisions_with_sinks", 0)))
