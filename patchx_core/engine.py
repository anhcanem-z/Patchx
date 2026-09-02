# -*- coding: utf-8 -*-
"""Dong co ap patch len cây APK da giai ma.

Cac tinh nang thong minh:
  - glob target (smali*/*.smali, res/values-*/strings.xml, ...);
  - component target: [LAUNCHER_ACTIVITIES], [ACTIVITIES], [APPLICATION];
  - bien MATCH_ASSIGN + khai trien ${GROUPn} / ${VAR};
  - dieu khien luong GOTO / MATCH_GOTO / DUMMY (nhan NAME);
  - idempotêncy (state.json), backup trước khi sua, dry-run;
  - MERGE co tai cau truc ID tai nguyen qua public.xml;
  - phat hien xung dot cung MATCH nhung khac REPLACE.
"""

import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass, field

from .model import Patch
from .smali_lib import (
    BOOL_LIT_RE,
    METHOD_RE,
    PARAM_TYPE_RE,
    _smali_escape,
    _smali_quote,
    _rewrite_bool,
    _smali_class_descriptor,
    _smali_target_rel,
    _find_method_block,
    _first_instruction_pos,
    _smali_alloc_temps,
    rewrite_pregs as _rewrite_pregs,
)

PSEUDO_TARGETS = {"[APPLICATION]", "[ACTIVITIES]", "[LAUNCHER_ACTIVITIES]"}

# Ket qua chuan hoa tung khối / toan bo patch (P1 — Unified contract)
RESULT_MATCHED = "MATCHED"          # khớp nhung khong doi (idempotênt/da dung)
RESULT_CHANGED = "CHANGED"          # da ap thay doi
RESULT_NO_MATCH = "NO_MATCH"        # quet nhung khong khớp
RESULT_SKIPPED = "SKIPPED"          # khối meta / khong lam gi
RESULT_FAILED = "FAILED"            # lỗi xay ra
RESULT_ROLLED_BACK = "ROLLED_BACK"  # STRICT: da rollback toan bo

META_TYPES = ("MIN_ENGINE_VER", "AUTHOR", "PACKAGE", "DUMMY")


@dataclass
class SectionResult:
    """Ket qua chuan hoa cua mot khối (section) trong patch."""
    type: str
    order: int
    status: str
    detail: str = ""


@dataclass
class ApplyResult:
    """Ket qua chuan hoa khi ap mot patch (P1 — Unified contract)."""
    patch: str
    status: str = RESULT_NO_MATCH
    files_scanned: int = 0
    matches: int = 0
    changes: int = 0
    files_changed: int = 0
    files_added: int = 0
    errors: int = 0
    warnings: int = 0
    rolled_back: bool = False
    passes_used: int = 0
    cycle_detected: bool = False
    sections: list = field(default_factory=list)

GROUP_RE = re.compile(r"\$\{GROUP(\d+)\}")
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
ACTIVITY_RE = re.compile(r"<activity\b([^>]*)>(.*?)</activity>", re.S)
NAME_RE = re.compile(r'android:name="([^"]+)"')
PACKAGE_RE = re.compile(r'package="([^"]+)"')
PUBLIC_RE = re.compile(
    r"<public\s+type=\"([^\"]+)\"\s+name=\"([^\"]+)\"\s+id=\"(0x[0-9a-fA-F]+)\"",
    re.S)
ID_RE = re.compile(r"\b0x[0-9a-fA-F]{8}\b")


# Directive khai bao thanh ghi trong than method
REG_DIR_RE = re.compile(r"^(\s*)\.(?:registers|locals)\s+\d+\s*$", re.M)


def _body_shape_ok(body, header=""):
    """Cau truc than method hop le de TRACE an toan.

    - dung MOT directive .registers/.locals, nam trong vung khai bao
      (trước lệnh/nhan dau tien);
    - khong co method long (dau .method/.end method) — file bi hong
      tu lần chay cu se duoc BO QUA, khong cham vao;
    - method abstract/native (khong co than) luon hop le.
    """
    if not body.strip() or re.search(r"\b(?:abstract|native)\b",
                                     header or ""):
        return True
    if re.search(r"(?m)^\s*\.(?:method|end method)\b", body):
        return False
    dirs = list(REG_DIR_RE.finditer(body))
    if len(dirs) != 1:
        return False
    m_instr = re.search(r"^\s*[^.#\s]", body, re.M)
    return not (m_instr and m_instr.start() < dirs[0].start())


MAX_PASSES = 5   # fixpoint: dung som khi NO_CHANGE; cham tran = nghi van cycle


def _remote_config_smali(url: str) -> str:
    """Sinh lop helper cau hinh tu xa (Lpatchx/RemoteConfig;) — mau de mo
    rong: nhan CONFIG_URL tu server, ap cau hinh, ghi log."""
    q = _smali_quote(url)
    return (
        "# Lop cau hinh tu xa do patchx sinh ra.\n"
        "# Mo rong: doc CONFIG_URL, tai cau hinh tu server, ap vao ung dung.\n"
        ".class public Lpatchx/RemoteConfig;\n"
        ".super Ljava/lang/Object;\n"
        "\n"
        ".field public static CONFIG_URL:Ljava/lang/String;\n"
        "\n"
        ".method static constructor <clinit>()V\n"
        "    .registers 1\n"
        "\n"
        "    const-string v0, %s\n"
        "    sput-object v0, Lpatchx/RemoteConfig;->CONFIG_URL:Ljava/lang/String;\n"
        "    return-void\n"
        ".end method\n"
        "\n"
        ".method public static init()V\n"
        "    .registers 2\n"
        "\n"
        "    const-string v0, \"patchx\"\n"
        "    sget-object v1, Lpatchx/RemoteConfig;->CONFIG_URL:Ljava/lang/String;\n"
        "    invoke-static {v0, v1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I\n"
        "    return-void\n"
        ".end method\n"
        "\n"
        ".method public static init(Landroid/content/Context;)V\n"
        "    .registers 2\n"
        "\n"
        "    const-string v0, \"patchx\"\n"
        "    sget-object v1, Lpatchx/RemoteConfig;->CONFIG_URL:Ljava/lang/String;\n"
        "    invoke-static {v0, v1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I\n"
        "    return-void\n"
        ".end method\n"
    ) % (q,)
   # quet nhieu luot: khối sau co the tao chuoi cho khối trước khớp


def _is_true(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


_META = set(".^$*+?{}[]()|\\")


def _literal_hint(pattern):
    """Trich chuoi literal dai nhat trong regex de loc file nhanh.

    Neu file khong chua chuoi nay thi regex chac chan khong khớp -> bo qua
    (tang toc dang ke tren APK lon). Khong trich khi co nhanh | o mức cao
    nhat (hint tu mot nhanh khong phai dieu kien can) va khong coi lop ky tu
    nhu \\d/\\w/\\s la literal co dinh.
    """
    best = ""
    cur = []
    i = 0
    n = len(pattern)
    depth = 0
    alt = {0: False}
    _LIT_ESCAPE = {"n": "\n", "t": "\t", "r": "\r",
                   ".": ".", "(": "(", ")": ")", "{": "{", "}": "}",
                   "[": "[", "]": "]", "$": "$", ">": ">", "<": "<",
                   '"': '"', "/": "/", "*": "*", "+": "+", "?": "?",
                   "^": "^", "-": "-", "|": "|", "\\": "\\"}

    def _flush():
        nonlocal best, cur
        if len(cur) > len(best):
            best = "".join(cur)
        cur = []

    while i < n:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            lit = _LIT_ESCAPE.get(nxt)
            if lit is None:
                _flush()
            elif lit == "\n":
                # Hint chua newline khong tim duoc bang rg -F (mot dong).
                _flush()
            else:
                cur.append(lit)
            i += 2
        elif ch == "(":
            _flush()
            depth += 1
            if i + 1 < n and pattern[i + 1] == "?" and \
                    i + 2 < n and pattern[i + 2] in ("=", "!"):
                alt[depth] = True   # lookahead: khong bat buoc
            else:
                alt[depth] = False
            i += 1
        elif ch == ")":
            if alt.get(depth):
                cur = []            # bo literal khong bat buoc trong nhóm
            else:
                _flush()            # literal trong nhóm thuong la bat buoc
            depth = max(0, depth - 1)
            i += 1
        elif ch == "|":
            # Alternation: literal trong nhanh khong bat buoc — danh dau nhóm
            # dang o mức depth va bo phan dang tich.
            if depth == 0:
                return ""           # nhanh top-level: khong co literal chung
            alt[depth] = True
            cur = []
            i += 1
        elif ch == "[":
            _flush()
            j = i + 1
            while j < n and pattern[j] != "]":
                j += 1
            i = j + 1
        elif ch in _META:
            _flush()
            i += 1
        else:
            cur.append(ch)
            i += 1
    _flush()
    return best if len(best) >= 6 else ""


class Engine:
    """Ap mot hoac nhieu patch len thu mức APK da giai ma."""

    def __init__(self, tree_root, *, dry_run=False, backup=True, force=False,
                 no_dex=True, dex_runner=None, strict=False, quiet=False,
                 reset_state=False, dex_timeout=60, dex_allow_extra=(),
                 allow_generated_target=False):
        self.tree_root = os.path.abspath(tree_root)
        self.dry_run = dry_run
        self.backup = backup and not dry_run
        self.force = force
        self.no_dex = no_dex
        self.dex_runner = dex_runner
        self.dex_timeout = dex_timeout
        self.dex_allow_extra = tuple(dex_allow_extra or ())
        self.strict = strict
        self.allow_generated_target = allow_generated_target
        self.quiet = quiet
        self.reset_state = reset_state
        self.vars = {}
        self.jumps = 0
        self.warnings = []
        self.errors = []
        self.changes = []          # (duong-dan, hanh-dong, chi-tiet)
        self.state_dir = os.path.join(self.tree_root, ".patchx")
        self.state_file = os.path.join(self.state_dir, "state.json")
        self.prov_file = os.path.join(self.state_dir, "provenance.json")
        self.backup_dir = os.path.join(
            self.state_dir, "backup", time.strftime("%Y%m%d-%H%M%S"))
        self.state = self._load_state()
        self.provenance = self._load_provenance()
        self._backed_up = set()
        self._file_index = None
        self._added_this_patch = set()
        self._added_files_all = set()
        self._pkg_cache = None
        self._pkg_cache_ok = False
        self._rsa_warned = False
        self._texts = {}
        self._TEXT_CACHE_MAX = 30000
        self._tx = None

    # ---- transaction (P2) ----
    def _tx_ensure(self):
        """Tu bat dau transaction neu chua co (helper goi truc tiep ngoai
        apply — vi du simulate dung cau truc ADD_FILES/MERGE)."""
        if self._tx is None:
            self._tx_start()

    def _tx_start(self):
        """Bat dau transaction cho mot patch: snapshot + thong ke + section."""
        self._tx = {
            "changes_start": len(self.changes),
            "scanned": 0,
            "matched": 0,
            "changed": 0,
            "files": {},          # rel -> noi dung cu (de rollback)
            "added": set(),       # rel tệp moi tao (xoa khi rollback)
            "files_changed": set(),  # rel da bi sua/xoa
            "state_keys": set(),  # key state them trong patch nay
            "sections": [],
            "rolled_back": False,
            "passes": 0,
            "cycle_detected": False,
        }

    def _tx_snapshot(self, rel):
        """Luu noi dung hien tai cua rel (lần dau) de rollback chinh xac."""
        if rel in self._tx["files"]:
            return
        p = os.path.join(self.tree_root, rel)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                self._tx["files"][rel] = fh.read()

    def _section_result(self, t, sec, before):
        """Chuyen delta cua mot khối thanh SectionResult chuan hoa."""
        c0, m0, s0, e0 = before
        if len(self.errors) > e0:
            return SectionResult(t, sec.order, RESULT_FAILED)
        if self._tx["changed"] > c0:
            return SectionResult(t, sec.order, RESULT_CHANGED)
        if self._tx["matched"] > m0:
            return SectionResult(t, sec.order, RESULT_MATCHED)
        if self._tx["scanned"] > s0:
            return SectionResult(t, sec.order, RESULT_NO_MATCH)
        return SectionResult(t, sec.order, RESULT_SKIPPED)

    def _rollback(self, patch, reason):
        """Khối phuc 100% moi thay doi cua patch hien tai (STRICT)."""
        tx = self._tx
        for rel, old in tx["files"].items():
            p = os.path.join(self.tree_root, rel)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(old)
            self._prov_record(rel, "rollback", patch)
        for rel in tx["added"]:
            p = os.path.join(self.tree_root, rel)
            if os.path.isfile(p):
                os.remove(p)
            self.provenance.pop(rel, None)
        for key in tx["state_keys"]:
            self.state.discard(key)
        self._texts.clear()
        self._invalidate_index()
        del self.changes[tx["changes_start"]:]
        self.changes.append(("<toan-bo-patch>", "rollback", reason))
        tx["rolled_back"] = True
        self._info("STRICT: da rollback toan bo thay doi cua patch %s (%s)"
                   % (patch.name, reason))

    def _build_result(self, patch):
        """Tong hop ApplyResult tu transaction hien tai."""
        tx = self._tx
        errs = sum(1 for s in tx["sections"] if s.status == RESULT_FAILED)
        if tx["rolled_back"]:
            status = RESULT_ROLLED_BACK
        elif errs:
            status = RESULT_FAILED
        elif tx["changed"]:
            status = RESULT_CHANGED
        elif tx["matched"]:
            status = RESULT_MATCHED
        elif tx["scanned"]:
            status = RESULT_NO_MATCH
        else:
            status = RESULT_SKIPPED
        result = ApplyResult(
            patch=patch.name,
            status=status,
            files_scanned=tx["scanned"],
            matches=tx["matched"],
            changes=tx["changed"],
            files_changed=len(tx["files_changed"]),
            files_added=len(tx["added"]),
            errors=errs,
            warnings=len(self.warnings),
            rolled_back=tx["rolled_back"],
            passes_used=tx["passes"],
            cycle_detected=tx["cycle_detected"],
            sections=list(tx["sections"]),
        )
        return result

    def _is_injected(self, rel):
        """Tep do ADD_FILES tao (patch hien tai hoac patch trước trong luot
        chay) — MATCH_REPLACE/MATCH_ASSIGN khong duoc quet vao tệp nay, tranh
        hook nham chinh class bo tro (vi du Fix.smali tu goi de quy)."""
        return rel in self._added_this_patch or rel in self._added_files_all

    # ---- thong bao ----
    def _info(self, msg):
        if not self.quiet:
            print("[patchx] " + msg)

    def _warn(self, msg):
        self.warnings.append(msg)
        if not self.quiet:
            print("[patchx] CẢNH BÁO: " + msg)

    def _error(self, msg):
        self.errors.append(msg)
        if not self.quiet:
            print("[patchx] LỖI: " + msg)

    # ---- trang thai / backup ----
    def _load_state(self):
        if self.reset_state:
            return set()
        try:
            with open(self.state_file, encoding="utf-8") as fh:
                return set(json.load(fh).get("applied", []))
        except Exception:
            return set()

    def _load_provenance(self):
        """P3 — ledger provenance: tệp nao do patch nao tao/sua, kem hash."""
        if self.reset_state:
            return {}
        try:
            with open(self.prov_file, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_provenance(self):
        if self.dry_run:
            return
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.prov_file, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.provenance, fh, ensure_ascii=False, indent=2)

    def _prov_record(self, rel, op, patch):
        """Ghi nhan thao tac len tệp vao ledger (P3 — Provenance)."""
        rel = self._safe_rel(rel) or rel
        rec = self.provenance.setdefault(rel, {
            "created_by": None,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "content_hash": None,
            "operations": [],
        })
        if op == "them" and rec.get("created_by") is None:
            rec["created_by"] = patch.name
        elif op in ("sua", "ghi-de", "xoa") and rec.get("created_by") is None:
            rec["created_by"] = "goc"
        if op == "xoa":
            rec["deleted"] = True
        elif rec.get("deleted"):
            rec["deleted"] = False
        p = os.path.join(self.tree_root, rel)
        if os.path.isfile(p):
            try:
                with open(p, "rb") as fh:
                    rec["content_hash"] = \
                        hashlib.sha256(fh.read()).hexdigest()[:16]
            except OSError:
                pass
        rec["operations"].append({
            "patch": patch.name,
            "op": op,
            "ts": time.strftime("%H:%M:%S"),
        })

    def _is_generated_foreign(self, rel, patch):
        """Tep do patch KHAC tao (theo ledger) — chan sua mac dinh (P3),
        tru khi force hoac allow_generated_target."""
        if self.force or self.allow_generated_target:
            return False
        rec = self.provenance.get(rel)
        cb = rec.get("created_by") if rec else None
        return bool(cb and cb != "goc" and cb != patch.name)

    def _save_state(self):
        if self.dry_run:
            return
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"applied": sorted(self.state)}, fh, ensure_ascii=False,
                      indent=2)
        self._save_provenance()

    def _backup(self, rel):
        if not self.backup or rel in self._backed_up:
            return
        src = os.path.join(self.tree_root, rel)
        if not os.path.isfile(src):
            return
        dst = os.path.join(self.backup_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            fout.write(fin.read())
        self._backed_up.add(rel)

    def _state_key(self, patch, sec, rel):
        h = hashlib.sha1()
        for part in (patch.source, patch.name, sec.type, str(sec.order), rel,
                     sec.get("TARGET"), sec.get("MATCH"), sec.get("REPLACE"),
                     sec.get("ASSIGN")):
            h.update(part.encode("utf-8", "replace"))
        return h.hexdigest()

    # ---- doc/ghi tệp an toan ----
    def _safe_rel(self, rel):
        rel = rel.replace("\\", "/")
        norm = os.path.normpath(rel)
        if norm.startswith("..") or os.path.isabs(norm):
            self._warn("bo qua duong dan khong an toan: " + rel)
            return None
        return norm

    def _read(self, path):
        if path in self._texts:
            return self._texts[path]
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if len(self._texts) < self._TEXT_CACHE_MAX:
            self._texts[path] = text
        return text

    def _commit(self, patch, sec, rel, path, new_text, count, key):
        self._tx_ensure()
        rel = self._safe_rel(rel) or rel
        self._run_done.add(key)
        self._tx["matched"] += count
        self._tx["changed"] += 1
        self._tx["files_changed"].add(rel)
        if self.dry_run:
            self.changes.append((rel, "sua", "thay %d cho" % count))
            return
        self._backup(rel)
        self._tx_snapshot(rel)
        self._texts.pop(path, None)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_text)
        self._prov_record(rel, "sua", patch)
        self.state.add(key)
        self._tx["state_keys"].add(key)
        self.changes.append((rel, "sua", "thay %d cho" % count))

    # ---- khai trien bien ----
    def _expand(self, value, m):
        out = value

        def sub_group(mm):
            try:
                return m.group(int(mm.group(1))) or ""
            except (IndexError, AttributeError):
                self._warn("GROUP%s khong ton tai trong ket qua khớp" % mm.group(1))
                return mm.group(0)

        out = GROUP_RE.sub(sub_group, out)

        def sub_var(mm):
            name = mm.group(1)
            if name in self.vars:
                return self.vars[name]
            self._warn("bien ${%s} chua duoc gan" % name)
            return mm.group(0)

        return VAR_RE.sub(sub_var, out)

    # ---- giai quyet target ----
    def _resolve_targets(self, pattern):
        """Giai quyet target theo cu phap glob cua APK Editor:
        dau * khớp MOI ky tu ke ca dau / (nen smali*/*.smali quet de quy)."""
        pattern = (pattern or "").strip()
        if not pattern:
            return []
        if pattern in PSEUDO_TARGETS:
            if pattern == "[LAUNCHER_ACTIVITIES]":
                return self._launcher_activity_smali()
            if pattern == "[ACTIVITIES]":
                return self._all_activity_smali()
            return ["AndroidManifest.xml"]
        if not glob.has_magic(pattern):
            p = os.path.join(self.tree_root, pattern)
            return [pattern] if os.path.isfile(p) else []
        rx = self._glob_regex(pattern)
        out = []
        for rel in self._iter_files():
            if rx.match(rel):
                out.append(rel)
        return sorted(set(out))

    def _iter_files(self):
        """Danh sach tệp (cache) — vo hieu hoa khi co thay doi cau truc."""
        if self._file_index is None:
            index = self._iter_files_fast()
            if index is None:
                index = []
                for root, _dirs, files in os.walk(self.tree_root):
                    if ".patchx" in root.split(os.sep):
                        continue
                    for f in files:
                        rel = os.path.relpath(os.path.join(root, f),
                                              self.tree_root)
                        index.append(rel)
            self._file_index = index
        return self._file_index

    def _iter_files_fast(self):
        """Liet ke tệp bang ripgrep (nhanh hon os.walk nhieu lần tren cây
        APK lon); tra None khi rg khong kha dung de dung duong os.walk."""
        import shutil as _shutil
        if not _shutil.which("rg"):
            return None
        try:
            out = subprocess.run(
                ["rg", "--files", "--no-messages", self.tree_root],
                capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0:
            return None
        rels = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rel = os.path.relpath(line, self.tree_root)
            except ValueError:
                continue
            if rel.startswith("..") or os.path.isabs(rel):
                continue
            rels.append(rel)
        return rels

    def _invalidate_index(self):
        self._file_index = None

    def _hint_files_rg(self, hint):
        """Tim nhanh cac file chua chuoi literal bang ripgrep (neu co).

        Tra danh sach relpath hoac None khi rg khong kha dung.
        """
        import shutil as _shutil
        if not _shutil.which("rg"):
            return None
        try:
            out = subprocess.run(
                ["rg", "-l", "-F", "--no-messages", hint, self.tree_root],
                capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode not in (0, 1):
            return None
        files = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rel = os.path.relpath(line, self.tree_root)
            except ValueError:
                continue
            if not rel.startswith("..") and not os.path.isabs(rel):
                files.append(rel)
        return files

    @staticmethod
    def _glob_regex(pattern):
        """Chuyen glob kieu APK Editor sang regex: * = moi chuoi (ke ca /)."""
        parts = []
        for ch in pattern:
            if ch == "*":
                parts.append(".*")
            elif ch == "?":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
        return re.compile("^" + "".join(parts) + "$")

    def _manifest_package(self, text):
        m = PACKAGE_RE.search(text)
        return m.group(1) if m else ""

    def _package_name(self):
        """Package cua cây APK (doc 1 lần, co cache)."""
        if not self._pkg_cache_ok:
            self._pkg_cache_ok = True
            self._pkg_cache = ""
            mpath = os.path.join(self.tree_root, "AndroidManifest.xml")
            if os.path.isfile(mpath):
                self._pkg_cache = self._manifest_package(self._read(mpath))
        return self._pkg_cache

    def _expand_package_placeholders(self, data):
        """Thay %PACKAGE_NAME% bang package that trong tai nguyen ADD_FILES/
        REPLACE_FILES (dinh dang Apk Editor). Tra (noi dung moi, da thay?).
        Khong thay neu tệp nhi phan hoac chua doc duoc package."""
        if isinstance(data, bytes):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return data, False
        else:
            text = data
        if "%PACKAGE_NAME%" not in text:
            return data, False
        pkg = self._package_name()
        if not pkg:
            self._warn("[engine] gap %PACKAGE_NAME% nhung khong doc duoc "
                       "package tu AndroidManifest.xml — giu nguyen.")
            return data, False
        return text.replace("%PACKAGE_NAME%", pkg).encode("utf-8"), True

    def _expand_rsa_placeholders(self, data):
        """Thay %RSA_DATA% bang cert DER hex cua APK goc (bien moi truong
        PATCHX_RSA_DATA) trong tai nguyen ADD_FILES/REPLACE_FILES.
        Khong co gia tri → giu nguyen (nhanh smali co try/catch nuot lỗi)."""
        if isinstance(data, bytes):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return data, False
        else:
            text = data
        if "%RSA_DATA%" not in text:
            return data, False
        rsa = os.environ.get("PATCHX_RSA_DATA", "").strip()
        if not rsa:
            if not self._rsa_warned:
                self._warn("[engine] gap %RSA_DATA% nhung chua co bien "
                           "PATCHX_RSA_DATA (cert DER hex APK goc) — giu "
                           "nguyen, spoof chu ky se khong hoat dong.")
                self._rsa_warned = True
            return data, False
        if not all(c in "0123456789abcdefABCDEF" for c in rsa) or len(rsa) % 2:
            self._warn("[engine] PATCHX_RSA_DATA khong phai hex hop le — "
                       "giu nguyen %RSA_DATA%.")
            return data, False
        return text.replace("%RSA_DATA%", rsa).encode("utf-8"), True

    @staticmethod
    def _resolve_class_name(name, pkg):
        if name.startswith("."):
            return pkg + name
        if "." not in name and pkg:
            return pkg + "." + name
        return name

    def _class_to_smali(self, names):
        roots = sorted(glob.glob(os.path.join(self.tree_root, "smali*")))
        if not roots:
            return []
        out = []
        for name in names:
            rel = name.replace(".", "/") + ".smali"
            found = False
            for root in roots:
                if os.path.isfile(os.path.join(root, rel)):
                    out.append(os.path.relpath(os.path.join(root, rel),
                                               self.tree_root))
                    found = True
                    break
            if not found:
                out.append(os.path.relpath(os.path.join(roots[0], rel),
                                           self.tree_root))
        return sorted(set(out))

    def _launcher_activity_smali(self):
        manifest = os.path.join(self.tree_root, "AndroidManifest.xml")
        if not os.path.isfile(manifest):
            return []
        text = self._read(manifest)
        pkg = self._manifest_package(text)
        names = []
        for m in ACTIVITY_RE.finditer(text):
            attrs, inner = m.groups()
            if ("android.intent.action.MAIN" in inner
                    and "android.intent.category.LAUNCHER" in inner):
                nm = NAME_RE.search(attrs)
                if nm:
                    names.append(self._resolve_class_name(nm.group(1), pkg))
        return self._class_to_smali(names)

    def _all_activity_smali(self):
        manifest = os.path.join(self.tree_root, "AndroidManifest.xml")
        if not os.path.isfile(manifest):
            return []
        text = self._read(manifest)
        pkg = self._manifest_package(text)
        names = []
        for m in ACTIVITY_RE.finditer(text):
            nm = NAME_RE.search(m.group(1))
            if nm:
                names.append(self._resolve_class_name(nm.group(1), pkg))
        return self._class_to_smali(names)

    resolve_targets = _resolve_targets

    # ---- ap patch chinh ----
    def apply(self, patch):
        self._check_conflicts(patch)
        self._tx_start()
        err0 = len(self.errors)
        labels = {}
        for i, s in enumerate(patch.sections):
            if s.name:
                labels.setdefault(s.name, i)
        # Marker per-run: moi rule chi xu ly 1 lần (quan trong cho dry-run)
        self._run_done = set()
        self._miss = {}
        self._added_this_patch = set()
        # Multi-pass: khối sau co the tao chuoi khien khối trước khớp o luot sau
        for _pass in range(MAX_PASSES):
            before = len(self.changes)
            i = 0
            seen = set()
            while i < len(patch.sections):
                if i in seen:
                    raise RuntimeError("Vòng lặp GOTO vượt giới hạn (patch: %s)"
                                       % patch.name)
                seen.add(i)
                sec = patch.sections[i]
                t = sec.type
                sb = (self._tx["changed"], self._tx["matched"],
                      self._tx["scanned"], len(self.errors))
                if t in META_TYPES:
                    i += 1
                elif t == "GOTO":
                    i = self._do_goto(patch, labels, sec, i)
                elif t == "MATCH_GOTO":
                    if self._match_present(sec):
                        i = self._do_goto(patch, labels, sec, i)
                    else:
                        i += 1
                elif t == "MATCH_REPLACE":
                    self._match_replace(patch, sec)
                    i += 1
                elif t == "MATCH_ASSIGN":
                    self._match_assign(patch, sec)
                    i += 1
                elif t == "ADD_FILES":
                    self._add_files(patch, sec)
                    i += 1
                elif t == "REPLACE_FILES":
                    self._replace_files(patch, sec)
                    i += 1
                elif t == "REMOVE_FILES":
                    self._remove_files(patch, sec)
                    i += 1
                elif t == "MERGE":
                    self._merge(patch, sec)
                    i += 1
                elif t == "EXECUTE_DEX":
                    self._execute_dex(patch, sec)
                    i += 1
                elif t == "SET_BOOL":
                    self._set_bool(patch, sec)
                    i += 1
                elif t == "INIT":
                    self._init(patch, sec)
                    i += 1
                elif t == "HOOK_SCRIPT":
                    self._hook_script(patch, sec)
                    i += 1
                elif t in ("TRACE", "API_LOG"):
                    self._trace(patch, sec, api=(t == "API_LOG"))
                    i += 1
                elif t == "REMOTE_CONFIG":
                    self._remote_config(patch, sec)
                    i += 1
                elif t in ("LAUNCHER_ACTIVITIES", "ACTIVITIES", "APPLICATION"):
                    self._component(patch, sec)
                    i += 1
                else:
                    self._warn("bo qua khối chua ho tro [%s] trong %s"
                               % (t, patch.name))
                    i += 1
                if _pass == 0:
                    self._tx["sections"].append(
                        self._section_result(t, sec, sb))
            if len(self.changes) == before:
                self._tx["passes"] = _pass + 1
                break
        else:
            self._tx["passes"] = MAX_PASSES
            self._tx["cycle_detected"] = True
            self._warn("fixpoint: patch %s đạt MAX_PASS=%d ma van con thay "
                       "doi — nghi van vong lap khong hoi tu"
                       % (patch.name, MAX_PASSES))
        result = self._build_result(patch)
        if self.strict and not self.dry_run and len(self.errors) > err0:
            self._rollback(patch, "strict voi %d lỗi"
                           % (len(self.errors) - err0))
            result.status = RESULT_ROLLED_BACK
            result.rolled_back = True
            for s in result.sections:
                if s.status in (RESULT_CHANGED, RESULT_MATCHED):
                    s.status = RESULT_ROLLED_BACK
        return result

    def apply_many(self, patches):
        for p in patches:
            self.apply(p)
        self.finalize()

    def _do_goto(self, patch, labels, sec, cur):
        label = sec.get("GOTO").strip()
        if label not in labels:
            raise RuntimeError("Nhan GOTO khong ton tai: %s (patch: %s)"
                               % (label, patch.name))
        self.jumps += 1
        return labels[label]

    def _check_conflicts(self, patch):
        groups = {}
        for sec in patch.sections:
            if sec.type != "MATCH_REPLACE":
                continue
            key = (sec.get("TARGET").strip(), sec.get("MATCH"),
                   sec.get("REGEX").strip())
            groups.setdefault(key, set()).add(sec.get("REPLACE"))
        for key, repls in groups.items():
            if len(repls) > 1:
                msg = "xung dot %s: cung MATCH nhung khac REPLACE (%d bien the)" \
                      % (key[0] or "<rỗng>", len(repls))
                self._warn("[%s] " % patch.name + msg)
                if self.strict:
                    self._error("[%s] " % patch.name + msg)

    def _match_present(self, sec):
        flags = re.DOTALL if _is_true(sec.get("DOTALL")) else 0
        try:
            compiled = re.compile(sec.get("MATCH"), flags) \
                if _is_true(sec.get("REGEX")) else None
        except re.error as e:
            self._warn("regex lỗi: %s" % e)
            return False
        hint = _literal_hint(sec.get("MATCH")) if compiled is not None else \
            sec.get("MATCH")
        for rel in self._resolve_targets(sec.get("TARGET")):
            if self._is_injected(rel):
                continue
            path = os.path.join(self.tree_root, rel)
            if not os.path.isfile(path):
                continue
            text = self._read(path)
            if hint and hint not in text:
                continue
            if compiled is not None:
                if compiled.search(text):
                    return True
            else:
                if sec.get("MATCH") in text:
                    return True
        return False

    def _replace_on(self, patch, sec, rel, compiled=None):
        path = os.path.join(self.tree_root, rel)
        if not os.path.isfile(path):
            self._warn("[%s] tệp khong ton tai: %s" % (patch.name, rel))
            return
        if self._is_generated_foreign(rel, patch):
            self._warn("[%s] chan sua tệp do patch khac tao: %s"
                       % (patch.name, rel))
            return
        key = self._state_key(patch, sec, rel)
        if not self.force and (key in self.state or key in self._run_done):
            return
        text = self._read(path)
        self._tx["scanned"] += 1
        match = sec.get("MATCH")
        replace = sec.get("REPLACE")
        if compiled is not None:
            hint = _literal_hint(match)
            if hint and hint not in text:
                return
            try:
                m = compiled.search(text)
            except re.error as e:
                self._error("[%s] regex lỗi o %s: %s" % (patch.name, rel, e))
                return
            if not m:
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                return
            repl = self._expand(replace, m)
            new_text = text[: m.start()] + repl + text[m.end():]
            count = 1
        else:
            if match not in text:
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                return
            repl = self._expand(replace, None)
            new_text = text.replace(match, repl)
            count = text.count(match)
        self._commit(patch, sec, rel, path, new_text, count, key)

    def _match_replace(self, patch, sec):
        targets = self._resolve_targets(sec.get("TARGET"))
        if not targets:
            self._warn("[%s] TARGET '%s' khong khớp tệp nao"
                       % (patch.name, sec.get("TARGET").strip() or "<rỗng>"))
            return
        compiled = None
        if _is_true(sec.get("REGEX")):
            flags = re.DOTALL if _is_true(sec.get("DOTALL")) else 0
            try:
                compiled = re.compile(sec.get("MATCH"), flags)
            except re.error as e:
                self._error("[%s] regex lỗi: %s" % (patch.name, e))
                return
        candidates = [rel for rel in targets if not self._is_injected(rel)]
        if compiled is not None:
            hint = _literal_hint(sec.get("MATCH"))
            if hint:
                rg_files = self._hint_files_rg(hint)
                if rg_files is not None:
                    rg_files = [rel for rel in rg_files
                                if not self._is_injected(rel)]
                    candidates = rg_files
        for rel in candidates:
            self._replace_on(patch, sec, rel, compiled=compiled)

    def _assign_on(self, patch, sec, rel, compiled=None):
        path = os.path.join(self.tree_root, rel)
        if not os.path.isfile(path):
            return
        if self._is_generated_foreign(rel, patch):
            self._warn("[%s] chan sua tệp do patch khac tao: %s"
                       % (patch.name, rel))
            return
        key = self._state_key(patch, sec, rel)
        if not self.force and (key in self.state or key in self._run_done):
            return
        text = self._read(path)
        self._tx["scanned"] += 1
        if compiled is not None:
            hint = _literal_hint(sec.get("MATCH"))
            if hint and hint not in text:
                return
        try:
            m = compiled.search(text) if compiled is not None else \
                re.search(sec.get("MATCH"), text)
        except re.error as e:
            self._error("[%s] regex lỗi o %s: %s" % (patch.name, rel, e))
            return
        if not m:
            k = (patch.source, sec.order)
            self._miss[k] = self._miss.get(k, 0) + 1
            return
        for part in sec.get("ASSIGN").splitlines():
            part = part.strip()
            if not part or "=" not in part:
                continue
            var, expr = part.split("=", 1)
            self.vars[var.strip()] = self._expand(expr.strip(), m)
        self._tx["matched"] += 1
        self._run_done.add(key)
        if not self.dry_run:
            self.state.add(key)
        self.changes.append((rel, "gan", list(self.vars.keys())[-1]))

    def _match_assign(self, patch, sec):
        flags = re.DOTALL if _is_true(sec.get("DOTALL")) else 0
        try:
            compiled = re.compile(sec.get("MATCH"), flags)
        except re.error as e:
            self._error("[%s] regex lỗi: %s" % (patch.name, e))
            return
        for rel in self._resolve_targets(sec.get("TARGET")):
            if self._is_injected(rel):
                continue
            self._assign_on(patch, sec, rel, compiled=compiled)

    def _get_asset(self, patch, src):
        src = (src or "").strip()
        if src in patch.assets:
            return patch.assets[src]
        if patch.asset_root:
            p = os.path.join(patch.asset_root, src)
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    return fh.read()
        return None

    def _add_files(self, patch, sec):
        self._tx_ensure()
        self._texts.clear()
        self._invalidate_index()
        src = sec.get("SOURCE").strip()
        dst = sec.get("TARGET").strip()
        if dst in ("", "/"):
            dst = "."
        elif os.path.isabs(dst) or ".." in dst:
            self._error("[%s] ADD_FILES: TARGET tuyet doi hoac chua '..' — "
                        "bo qua: %s" % (patch.name, dst))
            return
        data = self._get_asset(patch, src)
        if data is None:
            self._warn("[%s] khong tim thay tai nguyen SOURCE: %s"
                       % (patch.name, src))
            return
        added = skipped = 0
        if _is_true(sec.get("EXTRACT")):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                self._error("[%s] SOURCE khong phai zip hop le: %s"
                            % (patch.name, src))
                return
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                safe = self._safe_rel(name)
                if not safe:
                    continue
                # Tranh lap tien to: entry trong zip da chua TARGET
                # (vd TARGET=smali, entry=smali/apkeditor/...) — bo phan
                # trung trước khi noi, khong tao smali/smali/...
                dst_root = dst.rstrip("/")
                if dst_root not in ("", ".") and (
                        safe == dst_root
                        or safe.startswith(dst_root + "/")):
                    safe = safe[len(dst_root):].lstrip("/")
                if not safe:
                    continue
                out = os.path.join(self.tree_root, dst, safe)
                if os.path.exists(out) and not self.force:
                    skipped += 1
                    continue
                if self.dry_run:
                    rel_out = os.path.join(dst, safe)
                    self.changes.append((rel_out, "them", src))
                    self._added_this_patch.add(rel_out)
                    self._added_files_all.add(rel_out)
                    self._tx["changed"] += 1
                    self._tx["files_changed"].add(rel_out)
                    added += 1
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                content = zf.read(name)
                content, _ = self._expand_package_placeholders(content)
                content, _ = self._expand_rsa_placeholders(content)
                rel_out = os.path.join(dst, safe)
                if os.path.isfile(out):
                    self._tx_snapshot(rel_out)
                else:
                    self._tx["added"].add(rel_out)
                with open(out, "wb") as fh:
                    fh.write(content)
                added += 1
                self._prov_record(rel_out, "them", patch)
                self.changes.append((rel_out, "them", src))
                self._added_this_patch.add(rel_out)
                self._added_files_all.add(rel_out)
                self._tx["changed"] += 1
                self._tx["files_changed"].add(rel_out)
        else:
            safe = self._safe_rel(dst)
            if not safe or safe == ".":
                if safe == ".":
                    self._error("[%s] ADD_FILES: TARGET '%s' khong phai "
                                "duong dan tệp — can EXTRACT cho goc cây"
                                % (patch.name, dst))
                return
            out = os.path.join(self.tree_root, safe)
            if os.path.exists(out) and not self.force:
                self._info("[%s] bo qua tệp da ton tai: %s" % (patch.name, safe))
                return
            if self.dry_run:
                self.changes.append((safe, "them", src))
                self._added_this_patch.add(safe)
                self._added_files_all.add(safe)
                self._tx["changed"] += 1
                self._tx["files_changed"].add(safe)
                return
            os.makedirs(os.path.dirname(out), exist_ok=True)
            data, _ = self._expand_package_placeholders(data)
            data, _ = self._expand_rsa_placeholders(data)
            if os.path.isfile(out):
                self._tx_snapshot(safe)
            else:
                self._tx["added"].add(safe)
            with open(out, "wb") as fh:
                fh.write(data)
            self._prov_record(safe, "them", patch)
            self.changes.append((safe, "them", src))
            self._added_this_patch.add(safe)
            self._added_files_all.add(safe)
            self._tx["changed"] += 1
            self._tx["files_changed"].add(safe)
        if skipped:
            self._info("[%s] ADD_FILES: them %d, bo qua %d tệp da ton tai"
                       % (patch.name, added, skipped))

    def _remove_files(self, patch, sec):
        self._tx_ensure()
        self._texts.clear()
        self._invalidate_index()
        targets = self._resolve_targets(sec.get("TARGET"))
        if not targets:
            self._warn("[%s] REMOVE_FILES khong khớp tệp nao"
                       % patch.name)
            return
        for rel in targets:
            if rel == "AndroidManifest.xml" or rel.endswith("/AndroidManifest.xml"):
                self._warn("[%s] REMOVE_FILES: chan xoa tệp thiet yeu %s"
                           % (patch.name, rel))
                continue
            if self.dry_run:
                self.changes.append((rel, "xoa", "REMOVE_FILES"))
                self._tx["changed"] += 1
                self._tx["files_changed"].add(rel)
                continue
            self._backup(rel)
            self._tx_snapshot(rel)
            self._prov_record(rel, "xoa", patch)
            os.remove(os.path.join(self.tree_root, rel))
            self.changes.append((rel, "xoa", "REMOVE_FILES"))
            self._tx["changed"] += 1
            self._tx["files_changed"].add(rel)

    def _replace_files(self, patch, sec):
        """Ghi de tệp dich (co sao luu) — dung cho diff-apk sinh patch."""
        self._tx_ensure()
        self._texts.clear()
        self._invalidate_index()
        src = sec.get("SOURCE").strip()
        dst = sec.get("TARGET").strip()
        safe = self._safe_rel(dst)
        if not safe or safe == ".":
            self._error("[%s] REPLACE_FILES: TARGET '%s' khong phai duong "
                        "dan tệp" % (patch.name, dst))
            return
        data = self._get_asset(patch, src)
        if data is None:
            self._warn("[%s] khong tim thay tai nguyen SOURCE: %s"
                       % (patch.name, src))
            return
        out = os.path.join(self.tree_root, safe)
        if self.dry_run:
            self.changes.append((safe, "sua", src))
            self._tx["changed"] += 1
            self._tx["files_changed"].add(safe)
            return
        if os.path.exists(out):
            self._backup(safe)
            self._tx_snapshot(safe)
        else:
            self._tx["added"].add(safe)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        data, _ = self._expand_package_placeholders(data)
        data, _ = self._expand_rsa_placeholders(data)
        with open(out, "wb") as fh:
            fh.write(data)
        self._prov_record(safe, "ghi-de", patch)
        self.changes.append((safe, "sua", src))
        self._tx["changed"] += 1
        self._tx["files_changed"].add(safe)

    def _load_public_ids(self):
        p = os.path.join(self.tree_root, "res", "values", "public.xml")
        if not os.path.isfile(p):
            return {}
        try:
            text = self._read(p)
        except Exception:
            return {}
        return _parse_public(text)

    def _merge(self, patch, sec):
        self._tx_ensure()
        self._texts.clear()
        self._invalidate_index()
        src = sec.get("SOURCE").strip()
        data = self._get_asset(patch, src)
        if data is None:
            self._warn("[%s] khong tim thay tai nguyen MERGE: %s"
                       % (patch.name, src))
            return
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            self._error("[%s] SOURCE khong phai zip hop le: %s"
                        % (patch.name, src))
            return
        old_public = {}
        for n in zf.namelist():
            if n.lower() == "res/values/public.xml":
                try:
                    old_public = _parse_public(zf.read(n).decode("utf-8",
                                                                 errors="replace"))
                except Exception:
                    pass
        new_public = self._load_public_ids()
        id_map = {}
        if old_public and new_public:
            for key, old_id in old_public.items():
                if key in new_public:
                    id_map[old_id] = new_public[key]
        extracted = 0
        for n in zf.namelist():
            if n.endswith("/"):
                continue
            safe = self._safe_rel(n)
            if not safe:
                continue
            out = os.path.join(self.tree_root, safe)
            if os.path.exists(out) and not self.force:
                continue
            content = zf.read(n)
            if safe.endswith(".smali") and id_map:
                content = _refactor_ids(content, id_map)
            if self.dry_run:
                self.changes.append((safe, "them", "MERGE"))
                extracted += 1
                self._tx["changed"] += 1
                self._tx["files_changed"].add(safe)
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            if os.path.isfile(out):
                self._tx_snapshot(safe)
            else:
                self._tx["added"].add(safe)
            with open(out, "wb") as fh:
                fh.write(content)
            extracted += 1
            self._prov_record(safe, "them", patch)
            self.changes.append((safe, "them", "MERGE"))
            self._tx["changed"] += 1
            self._tx["files_changed"].add(safe)
        if id_map:
            self._info("[%s] MERGE: giai nen %d tệp, tai cau truc %d ID tai nguyen"
                       % (patch.name, extracted, len(id_map)))
        else:
            self._warn("[%s] MERGE: khong co public.xml de tai cau truc ID"
                       % patch.name)

    def _execute_dex(self, patch, sec):
        if self.no_dex:
            self._warn("[%s] bo qua EXECUTE_DEX (dung --dex-runner de chay): %s"
                       % (patch.name, sec.get("SCRIPT", "").strip()))
            return
        runner = (self.dex_runner or "").strip()
        if not runner:
            self._error("[%s] EXECUTE_DEX: thieu --dex-runner" % patch.name)
            return
        # Chong injection: runner phai la lệnh don (khong ky tu shell)
        if re.search(r"[;&|`$()<>!*?{}\[\]\\]", runner):
            self._error("[%s] EXECUTE_DEX: --dex-runner chua ky tu shell — "
                        "chi dung lệnh don (vi du: dex2jar, baksmali)"
                        % patch.name)
            return
        runner_path = shutil.which(runner)
        if not runner_path:
            self._error("[%s] EXECUTE_DEX: khong tim thay lệnh '%s'"
                        % (patch.name, runner))
            return
        # T5 — bo loc lệnh he thong: danh sach cho phep + cam ro rang
        allowed = {"dex2jar", "baksmali", "smali", "d8", "dexdump", "jadx"}
        blocked = {"sh", "bash", "zsh", "python", "python3", "perl", "ruby",
                   "rm", "cp", "mv", "wget", "curl", "nc", "telnet", "cat",
                   "echo", "chmod", "chown", "dd", "mkfs"}
        if runner in blocked:
            self._error("[%s] EXECUTE_DEX: lệnh '%s' nam trong danh sach cam "
                        "(bao ve chuoi cung ung)." % (patch.name, runner))
            return
        if runner not in allowed and runner not in self.dex_allow_extra:
            self._error("[%s] EXECUTE_DEX: lệnh '%s' khong nam danh sach cho "
                        "phep %s — dung --dex-allow <lệnh> de mo rong."
                        % (patch.name, runner, sorted(allowed)))
            return
        cmd = [runner, patch.source, self.tree_root,
               sec.get("MAIN_CLASS", "").strip(),
               sec.get("ENTRANCE", "").strip(),
               sec.get("PARAM", "").strip()]
        try:
            import tempfile
            with tempfile.TemporaryDirectory(
                    prefix="patchx_dex_sandbox_") as sandbox:
                subprocess.run(cmd, check=True, timeout=self.dex_timeout,
                               cwd=sandbox)
            self.changes.append(("dex", "chay", cmd[3]))
            self._tx["changed"] += 1
        except subprocess.TimeoutExpired as e:
            self._error("[%s] EXECUTE_DEX qua thoi gian (%ss): %s"
                        % (patch.name, self.dex_timeout, cmd[0]))
        except (OSError, subprocess.CalledProcessError) as e:
            self._error("[%s] EXECUTE_DEX that bai: %s" % (patch.name, e))

    # ---- khối thuc thi hien dai ----
    def _application_smali(self):
        """Tim smali cua lop Application khai bao trong manifest."""
        manifest = os.path.join(self.tree_root, "AndroidManifest.xml")
        if not os.path.isfile(manifest):
            return []
        text = self._read(manifest)
        pkg = self._manifest_package(text)
        m = re.search(r"<application\b([^>]*)>", text, re.S)
        if not m:
            return []
        nm = NAME_RE.search(m.group(1))
        if not nm:
            return []
        return self._class_to_smali(
            [self._resolve_class_name(nm.group(1), pkg)])

    def _set_bool(self, patch, sec):
        """SET_BOOL: doi literal boolean (true/false/0x0/0x1/1/0) trong vung
        MATCH sang VALUE — idempotênt vi sau khi doi MATCH cu khong con khớp."""
        value = sec.get("VALUE").strip().lower()
        if value not in ("true", "false", "1", "0", "0x0", "0x1"):
            self._error("[%s] SET_BOOL: VALUE khong hop le: %r (dung "
                        "true/false/1/0/0x0/0x1)" % (patch.name, value))
            return
        want = value in ("true", "1", "0x1")
        targets = self._resolve_targets(sec.get("TARGET"))
        if not targets:
            self._warn("[%s] SET_BOOL: TARGET '%s' khong khớp tệp nao"
                       % (patch.name, sec.get("TARGET").strip() or "<rỗng>"))
            return
        compiled = None
        if _is_true(sec.get("REGEX")):
            flags = re.DOTALL if _is_true(sec.get("DOTALL")) else 0
            try:
                compiled = re.compile(sec.get("MATCH"), flags)
            except re.error as e:
                self._error("[%s] SET_BOOL: regex lỗi: %s" % (patch.name, e))
                return
        for rel in targets:
            self._set_bool_on(patch, sec, rel, compiled, want)

    def _set_bool_on(self, patch, sec, rel, compiled, want):
        path = os.path.join(self.tree_root, rel)
        if not os.path.isfile(path):
            return
        if self._is_generated_foreign(rel, patch):
            self._warn("[%s] chan sua tệp do patch khac tao: %s"
                       % (patch.name, rel))
            return
        key = self._state_key(patch, sec, rel)
        if not self.force and (key in self.state or key in self._run_done):
            return
        text = self._read(path)
        self._tx["scanned"] += 1
        match = sec.get("MATCH")
        if compiled is not None:
            hint = _literal_hint(match)
            if hint and hint not in text:
                return
            m = compiled.search(text)
            if not m:
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                return
            new_text = text[:m.start()] + _rewrite_bool(m.group(0), want) \
                + text[m.end():]
            count = 1
        else:
            if match not in text:
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                return
            new_text = text.replace(match, _rewrite_bool(match, want))
            count = text.count(match)
        if new_text == text:
            self._tx["matched"] += count
            return
        self._commit(patch, sec, rel, path, new_text, count, key)

    def _inject_into_method(self, patch, sec, rel, method, lines, marker):
        """Chen cac dong smali vao dau than method (sau moi directive) —
        idempotênt theo marker. Tra True neu da chen."""
        path = os.path.join(self.tree_root, rel)
        if not os.path.isfile(path):
            self._warn("[%s] tệp khong ton tai: %s" % (patch.name, rel))
            return False
        key = self._state_key(patch, sec, rel)
        if not self.force and (key in self.state or key in self._run_done):
            return False
        text = self._read(path)
        if marker and marker in text:
            return False
        m = _find_method_block(text, method)
        if not m:
            k = (patch.source, sec.order)
            self._miss[k] = self._miss.get(k, 0) + 1
            return False
        pos = _first_instruction_pos(text, m.start(4), m.end(4))
        block = ""
        if marker:
            block += "    " + marker + "\n"
        block += "\n".join("    " + ln if ln.strip() else ln
                           for ln in lines) + "\n"
        new_text = text[:pos] + block + text[pos:]
        self._commit(patch, sec, rel, path, new_text, 1, key)
        return True

    def _init(self, patch, sec):
        """INIT: chen CODE vao dau than METHOD (mac dinh onCreate) cua TARGET
        (mac dinh [LAUNCHER_ACTIVITIES])."""
        code = sec.get("CODE")
        if not code.strip():
            self._warn("[%s] INIT: CODE rong" % patch.name)
            return
        method = (sec.get("METHOD") or "").strip() or "onCreate"
        targets = self._resolve_targets(sec.get("TARGET"))
        if not targets:
            targets = self._launcher_activity_smali()
        if not targets:
            self._warn("[%s] INIT: khong tim thay target (TARGET rong va "
                       "khong co launcher activity)" % patch.name)
            return
        marker = "# patchx-init:" + hashlib.sha1(
            code.encode("utf-8")).hexdigest()[:12]
        for rel in targets:
            self._inject_into_method(patch, sec, rel, method,
                                     code.split("\n"), marker)

    def _hook_script(self, patch, sec):
        """HOOK_SCRIPT: ghi asset SOURCE (smali) vao cây va chen lỗi goi
        invoke-static ENTRY (mac dinh onCreate()V) vao METHOD (mac dinh
        onCreate) cua TARGET (mac dinh [LAUNCHER_ACTIVITIES])."""
        src = sec.get("SOURCE").strip()
        data = self._get_asset(patch, src)
        if data is None:
            self._warn("[%s] khong tim thay tai nguyen SOURCE: %s"
                       % (patch.name, src))
            return
        try:
            smali_text = data.decode("utf-8")
        except UnicodeDecodeError:
            self._error("[%s] HOOK_SCRIPT: SOURCE khong phai UTF-8: %s"
                        % (patch.name, src))
            return
        cls = _smali_class_descriptor(smali_text)
        if not cls:
            self._error("[%s] HOOK_SCRIPT: khong tim thay khai bao .class "
                        "trong %s" % (patch.name, src))
            return
        entry = (sec.get("ENTRY") or "").strip() or "onCreate"
        # 1) Ghi tệp smali hook vao cây (bo qua neu da ton tai)
        rel = _smali_target_rel(self.tree_root, cls)
        out = os.path.join(self.tree_root, rel)
        if os.path.exists(out) and not self.force:
            self._info("[%s] HOOK_SCRIPT: tệp da ton tai, giu nguyen: %s"
                       % (patch.name, rel))
        else:
            self._invalidate_index()
            if self.dry_run:
                self.changes.append((rel, "them", src))
                self._tx["changed"] += 1
                self._tx["files_changed"].add(rel)
            else:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if os.path.isfile(out):
                    self._tx_snapshot(rel)
                else:
                    self._tx["added"].add(rel)
                with open(out, "wb") as fh:
                    fh.write(data)
                self._prov_record(rel, "them", patch)
                self.changes.append((rel, "them", src))
                self._tx["changed"] += 1
                self._tx["files_changed"].add(rel)
        # 2) Chen lỗi goi invoke-static vao target
        call = "invoke-static {}, L%s;->%s()V" % (cls, entry)
        marker = "# patchx-hook:" + hashlib.sha1(
            call.encode("utf-8")).hexdigest()[:12]
        method = (sec.get("METHOD") or "").strip() or "onCreate"
        targets = self._resolve_targets(sec.get("TARGET"))
        if not targets:
            targets = self._launcher_activity_smali()
        for rel_t in targets:
            self._inject_into_method(patch, sec, rel_t, method, [call], marker)

    def _trace(self, patch, sec, api=False):
        """TRACE / API_LOG: chen log quanh dong khớp MATCH.

        - TRACE: ghi lai dong lệnh (invoke-*/goi ham) khớp mau;
        - API_LOG: ghi lai chuoi URL / lỗi goi API khớp mau.
        Log dung Log.d(TAG, msg); moi method duoc cap 2 thanh ghi tam an toan.
        """
        tag = (sec.get("TAG") or "").strip() or "patchx"
        targets = self._resolve_targets(sec.get("TARGET"))
        if not targets:
            self._warn("[%s] %s: TARGET '%s' khong khớp tệp nao"
                       % (patch.name, sec.type,
                          sec.get("TARGET").strip() or "<rỗng>"))
            return
        compiled = None
        if _is_true(sec.get("REGEX")):
            try:
                compiled = re.compile(sec.get("MATCH"))
            except re.error as e:
                self._error("[%s] %s: regex lỗi: %s"
                            % (patch.name, sec.type, e))
                return
            hint = _literal_hint(sec.get("MATCH"))
            if hint:
                rg_files = self._hint_files_rg(hint)
                if rg_files is not None:
                    candidates = [rel for rel in rg_files
                                  if not self._is_injected(rel)]
                    if candidates:
                        targets = candidates
                    else:
                        targets = []
        after = _is_true(sec.get("AFTER"))
        for rel in targets:
            self._trace_on(patch, sec, rel, compiled, tag, after, api)

    def _trace_on(self, patch, sec, rel, compiled, tag, after, api):
        path = os.path.join(self.tree_root, rel)
        if not os.path.isfile(path):
            return
        if self._is_generated_foreign(rel, patch):
            self._warn("[%s] chan sua tệp do patch khac tao: %s"
                       % (patch.name, rel))
            return
        key = self._state_key(patch, sec, rel)
        if not self.force and (key in self.state or key in self._run_done):
            return
        text = self._read(path)
        self._tx["scanned"] += 1
        match = sec.get("MATCH")
        # Gom moi method can sua, roi ap TU CUOI LEN DAU — neu ap theo thu tu
        # xuoi, offset (b_start/b_end) cua cac match sau bi lech vi body trước
        # da dai hon -> chen nham vi tri, nuot .end method/header method.
        edits = []
        inserted = 0
        for m in list(METHOD_RE.finditer(text)):
            header, sig = m.group(1), m.group(3)
            b_start, b_end = m.start(4), m.end(4)
            body = m.group(4)
            if not _body_shape_ok(body, header):
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                continue
            lines = body.split("\n")
            hits = []
            for idx, ln in enumerate(lines):
                if not ln.strip():
                    continue
                if ln.lstrip().startswith((".", "#", ":")):
                    continue
                if compiled is not None:
                    mm = compiled.search(ln)
                    if not mm:
                        continue
                    msg = (mm.group(1) if mm.re.groups
                           and mm.group(1) is not None
                           else mm.group(0)).strip()
                else:
                    if match not in ln:
                        continue
                    msg = ln.strip()
                if not msg:
                    continue
                hits.append((idx, msg))
            if not hits:
                continue
            reg_line, temps, reg_m, pregs = _smali_alloc_temps(
                body, sig, "static" in header)
            if reg_line is None:
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                continue
            insert_map = {}
            n_blocks = 0
            for idx, msg in hits:
                msg = msg[:300]
                marker = ("# patchx-api:" if api else "# patchx-trace:") \
                    + hashlib.sha1((tag + "|" + msg).encode("utf-8")
                                   ).hexdigest()[:12]
                if marker in text:
                    continue
                v0, v1 = temps
                if v0 > 255 or v1 > 255:
                    # const-string chi 8-bit thanh ghi — bo qua method qua lon
                    k = (patch.source, sec.order)
                    self._miss[k] = self._miss.get(k, 0) + 1
                    continue
                if v0 >= 16 or v1 >= 16:
                    # invoke-static {..} gioi han v15 (opcode 35c) — dung /range
                    invoke = ("    invoke-static/range {v%d .. v%d}, "
                              "Landroid/util/Log;->d(Ljava/lang/String;"
                              "Ljava/lang/String;)I\n" % (v0, v1))
                else:
                    invoke = ("    invoke-static {v%d, v%d}, "
                              "Landroid/util/Log;->d(Ljava/lang/String;"
                              "Ljava/lang/String;)I\n" % (v0, v1))
                block = "    %s\n" % marker
                block += "    const-string v%d, %s\n" \
                    % (v0, _smali_quote(tag))
                block += "    const-string v%d, %s\n" \
                    % (v1, _smali_quote(msg))
                block += invoke
                at = idx + 1 if after else idx
                insert_map.setdefault(at, []).append(block)
                n_blocks += 1
            if not n_blocks:
                continue
            out_lines = []
            for idx, ln in enumerate(lines):
                if reg_m is not None and reg_m.group(0).rstrip("\n") == ln:
                    out_lines.append(reg_line)
                elif pregs:
                    out_lines.append(_rewrite_pregs(ln, pregs))
                else:
                    out_lines.append(ln)
            final = []
            for idx, ln in enumerate(out_lines):
                for blk in insert_map.get(idx, []):
                    final.append(blk)
                final.append(ln)
            for blk in insert_map.get(len(out_lines), []):
                final.append(blk)
            body_new = "\n".join(final)
            if not _body_shape_ok(body_new):
                k = (patch.source, sec.order)
                self._miss[k] = self._miss.get(k, 0) + 1
                continue
            edits.append((b_start, b_end, body_new))
            inserted += n_blocks
        if inserted == 0:
            return
        new_text = text
        for b_start, b_end, body_new in reversed(edits):
            new_text = new_text[:b_start] + body_new + new_text[b_end:]
        self._commit(patch, sec, rel, path, new_text, inserted, key)

    def _remote_config(self, patch, sec):
        """REMOTE_CONFIG: tao helper smali chua CONFIG_URL (Lpatchx/RemoteConfig;)
        va chen init vao METHOD cua TARGET — [APPLICATION] mac dinh
        attachBaseContext (truyen {p1} Context), con lai onCreate()V."""
        url = sec.get("CONFIG_URL").strip()
        if not url:
            self._warn("[%s] REMOTE_CONFIG: CONFIG_URL rong" % patch.name)
            return
        method = (sec.get("METHOD") or "").strip()
        target = sec.get("TARGET").strip()
        if target == "[APPLICATION]":
            method = method or "attachBaseContext"
            targets = self._application_smali() or self._launcher_activity_smali()
        else:
            method = method or "onCreate"
            targets = self._resolve_targets(target)
            if not targets:
                targets = self._launcher_activity_smali()
        # 0) Ep gia tri boolean tai moi điểm READ — khong phu thuoc target
        self._force_flags(patch, sec)
        # HELPER: false → chi ep flag, KHONG tao helper/init (app cham tran
        # 64K method ref — them class/method moi lam tran dex).
        if not _is_true(sec.get("HELPER") or "true"):
            self._info("[%s] REMOTE_CONFIG: HELPER=false — chi ep flag, "
                       "khong them helper/init" % patch.name)
            return
        if not targets:
            self._warn("[%s] REMOTE_CONFIG: khong tim thay target de chen init"
                       % patch.name)
            return
        # 1) Ghi helper smali
        rel = _smali_target_rel(self.tree_root, "patchx/RemoteConfig")
        out = os.path.join(self.tree_root, rel)
        if os.path.exists(out) and not self.force:
            self._info("[%s] REMOTE_CONFIG: helper da ton tai, giu nguyen: %s"
                       % (patch.name, rel))
        else:
            self._invalidate_index()
            if self.dry_run:
                self.changes.append((rel, "them", "REMOTE_CONFIG"))
                self._tx["changed"] += 1
                self._tx["files_changed"].add(rel)
            else:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if os.path.isfile(out):
                    self._tx_snapshot(rel)
                else:
                    self._tx["added"].add(rel)
                with open(out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(_remote_config_smali(url))
                self._prov_record(rel, "them", patch)
                self.changes.append((rel, "them", "REMOTE_CONFIG"))
                self._tx["changed"] += 1
                self._tx["files_changed"].add(rel)
        # 2) Chen lỗi goi init
        if method == "attachBaseContext":
            call = ("invoke-static {p1}, Lpatchx/RemoteConfig;->init"
                    "(Landroid/content/Context;)V")
        else:
            call = "invoke-static {}, Lpatchx/RemoteConfig;->init()V"
        marker = "# patchx-rconfig:" + hashlib.sha1(
            (url + "|" + method).encode("utf-8")).hexdigest()[:12]
        for rel_t in targets:
            self._inject_into_method(patch, sec, rel_t, method, [call], marker)

    def _force_flags(self, patch, sec):
        """FORCE trong REMOTE_CONFIG: ep gia tri boolean tai moi điểm doc
        (sget-boolean/iget-boolean) cua cac flag duoc liet ke.

        Moi dong FORCE co dang:  Lcls;->tên:Z = true|false
        Diem doc nam sau lop giai ma/payload → bat chap ma hoa tren duong
        truyen, va gia tri ep de toan bo nguon ghi (server, prefs, ...).
        """
        spec = sec.get("FORCE") or ""
        forces = []
        for line in spec.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                self._error("[%s] FORCE thieu '=': %r (dung "
                            "Lcls;->fld:Z = true|false)" % (patch.name, line))
                continue
            field, _, val = line.partition("=")
            field = field.strip()
            val = val.strip().lower()
            if not re.match(r"^L[^;]+;->[A-Za-z0-9_$]+:Z$", field):
                self._error("[%s] FORCE field khong hop le: %r (phai la "
                            "Lcls;->fld:Z)" % (patch.name, field))
                continue
            if val not in ("true", "false", "1", "0", "0x1", "0x0"):
                self._error("[%s] FORCE gia tri khong hop le: %r (dung "
                            "true|false|1|0|0x1|0x0)" % (patch.name, val))
                continue
            forces.append((field, val in ("true", "1", "0x1")))
        if not forces:
            return
        rels = self._iter_files()
        smali_rels = [rel for rel in rels if rel.endswith(".smali")]
        for field, want in forces:
            lit = field
            hits = self._hint_files_rg(lit)
            candidates = hits if hits is not None else smali_rels
            rx = re.compile(
                r"^(\s*)(?:sget|iget)-boolean\s+(v\d+)"
                r"(?:,\s*[vp]\d+)?,\s*" + re.escape(field) + r"\s*$",
                re.MULTILINE)
            lit_const = "0x1" if want else "0x0"

            def _force_repl(m):
                reg = m.group(2)
                num = int(reg[1:])
                if num > 255:
                    return m.group(0)  # qua cao cho const 8-bit — giu nguyen
                op = "const/4" if num < 16 else "const/16"
                return "%s%s %s, %s" % (m.group(1), op, reg, lit_const)

            for rel in candidates:
                path = os.path.join(self.tree_root, rel)
                if not os.path.isfile(path) or self._is_injected(rel):
                    continue
                key = hashlib.sha1((
                    "force|" + patch.source + "|" + patch.name + "|"
                    + sec.type + "|" + str(sec.order) + "|" + field + "|"
                    + lit_const + "|" + rel).encode("utf-8")).hexdigest()
                if not self.force and (key in self.state or key in self._run_done):
                    continue
                text = self._read(path)
                new_text, n = rx.subn(_force_repl, text)
                if n == 0:
                    continue
                self._commit(patch, sec, rel, path, new_text, n, key)
                self._info("[%s] FORCE %s = %s: sua %d điểm doc trong %s"
                           % (patch.name, field, lit_const, n, rel))

    def _component(self, patch, sec):
        # Cac khối component hoat dong tren AndroidManifest.xml
        rel = "AndroidManifest.xml"
        if "ASSIGN" in sec.body:
            self._assign_on(patch, sec, rel)
        if "REPLACE" in sec.body or "MATCH" in sec.body:
            self._replace_on(patch, sec, rel)

    def finalize(self):
        if not self.dry_run:
            self._save_state()
        if self.quiet:
            return
        n = len(self.changes)
        if self.dry_run:
            print("[patchx] (dry-run) du kien %d thay doi" % n)
        else:
            print("[patchx] da ap %d thay doi" % n)
        if self.warnings:
            print("[patchx] %d canh bao" % len(self.warnings))
        if self._miss and not self.quiet:
            total_miss = sum(self._miss.values())
            print("[patchx] %d rule khong khớp tren %d file (bo qua)"
                  % (len(self._miss), total_miss))
        if self.errors:
            print("[patchx] %d lỗi" % len(self.errors))


def _parse_public(text):
    out = {}
    for m in PUBLIC_RE.finditer(text):
        out[(m.group(1), m.group(2))] = m.group(3)
    return out


def _refactor_ids(content, id_map):
    def repl(m):
        return id_map.get(m.group(0), m.group(0))
    return ID_RE.sub(repl, content)
