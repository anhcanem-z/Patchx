# -*- coding: utf-8 -*-
"""Thu vien tien ich smali dung chung cho patchx.

Muc dich: gom cac thao tac smali lap lai (tim method, cap thanh ghi an toan,
tim call-site, chen invoke co kiem tra kieu) vao mot noi de cac module khac
dung chung, tranh sao chep logic.

Quy uoc: binh luan va thong bao tieng Viet; chuoi smali/regex giu nguyen goc.
"""

import glob
import hashlib
import os
import re

# Bien the boolean trong smali: 0x0/0x1, true/false, hoac so nguyen 0/1
BOOL_LIT_RE = re.compile(r"\b(0x0[01]|0x[01]|true|false|[01])\b")

# Khối method smali: header + than toi .end method
METHOD_RE = re.compile(
    r"(?m)^(\s*\.method[^\n]*?\s([A-Za-z_$<][A-Za-z0-9_$<>]*)"
    r"(\([^)]*\))[^\n]*)\n(.*?)^(\s*\.end method)",
    re.S)

# Kieu tham so trong chu ky smali: dung de dem so thanh ghi khi chuyen .locals
PARAM_TYPE_RE = re.compile(r"(\[*L[^;]*;|\[*[BCDFIJSZV])")

# Mot lỗi goi smali: invoke-... {registers}, Lclass;->method(...)ret
CALL_SITE_RE = re.compile(
    r"(?m)^(\s*)(invoke-(?:virtual|static|direct|super|interface|range|"
    r"custom))\s*\{([^}]*)\},\s*L([^;]+);->([^(\s]+)\(([^)]*)\)([^\n]*)")


def smali_escape(text):
    """Thoat chuoi cho literal smali (dau gach cheo + nhay kep)."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def smali_quote(text):
    """Boc chuoi thanh literal smali: "..." (da thoat)."""
    return '"' + smali_escape(text) + '"'


def rewrite_bool(text, want_true):
    """Doi moi literal boolean trong vung MATCH sang ho tuong ung voi VALUE.

    0x0/0x1 giu ho hex, 0/1 giu ho so, true/false giu ho tu khoa.
    """
    def repl(m):
        tok = m.group(0)
        if tok in ("0x0", "0x1"):
            return "0x1" if want_true else "0x0"
        if tok in ("1", "0"):
            return "1" if want_true else "0"
        return "true" if want_true else "false"

    return BOOL_LIT_RE.sub(repl, text)


def smali_class_descriptor(text):
    """Trich tên class tu khai bao .class — tra 'com/demo/Hook' hoac None."""
    m = re.search(r"\.class\b[^\n]*?\bL([^;\s]+);", text)
    return m.group(1) if m else None


def smali_target_rel(tree_root, cls):
    """Duong dan tuong doi cho class smali (Lcom/x/Y; -> smali/com/x/Y.smali).

    Uu tien thu mức smali* co san (thuong la smali/).
    """
    roots = sorted(glob.glob(os.path.join(tree_root, "smali*")))
    root = os.path.basename(roots[0]) if roots else "smali"
    return os.path.join(root, cls.replace(".", "/") + ".smali")


def find_method_block(text, method):
    """Tim khối method theo tên — tra match cua METHOD_RE hoac None."""
    for m in METHOD_RE.finditer(text):
        if m.group(2) == method:
            return m
    return None


def first_instruction_pos(text, body_start, body_end):
    """Vi tri chen an toan trong than method.

    Chen ngay TRUOC lệnh dau tien, sau moi directive .registers/.locals/
    .param/.annotation va chu thich.
    """
    body = text[body_start:body_end]
    m = re.search(r"(?m)^\s*[^.\s#]", body)
    return body_start + m.start() if m else body_end


def _param_count(sig, is_static):
    params = sig[sig.find("(") + 1:sig.rfind(")")]
    return len(PARAM_TYPE_RE.findall(params)) + (0 if is_static else 1)


# pX dung lam thanh ghi: dung sau khoang trang/{/phay, dung trước khoang
# trang/,/}/:/] hoac cuoi dong — tranh nham tên field Lcls;->p1:Z hay chuoi.
PREG_RE = re.compile(r"(?<=[\s{,])p(\d+)(?=[\s,}\]:]|$)")


def rewrite_pregs(line, pregs):
    """Doi pX thanh vN tuong minh theo bo cuc thanh ghi GOC (trước khi nang
    .registers) — giu nguyen anh xa cua moi lệnh hien co khi them thanh ghi."""
    if not pregs:
        return line

    def repl(m):
        i = int(m.group(1))
        v = pregs.get(i)
        return "v%d" % v if v is not None else m.group(0)

    return PREG_RE.sub(repl, line)


def smali_alloc_temps(body, sig, is_static):
    """Cap 2 thanh ghi tam an toan cho method smali.

    - .registers N  -> .registers N+2, dung vN/vN+1 (cao nhat, khong dung).
    - .locals L     -> chuyen sang .registers L+P, dung v(L+P)/v(L+P+1).
    Tra (dong .registers moi, (v0, v1), match dong cu, ban do pX -> vN goc)
    hoac (None, None, None, None) khi khong khai bao .registers/.locals.

    Quan trong: nang .registers lam DICH anh xa pX (pX = v(locals+X)) — phai
    viet lai pX thanh vN tuong minh theo bo cuc goc, neu khong pX truot len
    v16+ (vuot gioi han opcode 4-bit) va dung thanh ghi tam moi.
    """
    m = re.search(r"^(\s*)\.registers\s+(\d+)(\s*)$", body, re.M)
    if m:
        n = int(m.group(2))
        p = _param_count(sig, is_static)
        pregs = {i: n - p + i for i in range(p)}
        return m.group(1) + ".registers %d" % (n + 2), (n, n + 1), m, pregs
    m = re.search(r"^(\s*)\.locals\s+(\d+)(\s*)$", body, re.M)
    if m:
        n = int(m.group(2))
        p = _param_count(sig, is_static)
        pregs = {i: n + i for i in range(p)}
        total = n + p
        return m.group(1) + ".registers %d" % (total + 2), \
            (total, total + 1), m, pregs
    return None, None, None, None


def find_call_sites(text, class_desc, method_name=None):
    """Tim moi call-site toi L<class>;->method(...).

    Tra danh sach dict gom: start, end, line, registers, invoke_type, class,
    method, params, return_type.
    """
    out = []
    for m in CALL_SITE_RE.finditer(text):
        cls = m.group(4)
        method = m.group(5)
        if cls != class_desc:
            continue
        if method_name and method != method_name:
            continue
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end == -1:
            line_end = len(text)
        out.append({
            "start": m.start(),
            "end": m.end(),
            "line": text[line_start:line_end].rstrip("\r\n"),
            "registers": [r.strip() for r in m.group(3).split(",")
                          if r.strip()],
            "invoke_type": m.group(2),
            "class": cls,
            "method": method,
            "params": m.group(6),
            "return_type": m.group(7).strip(),
        })
    return out


def insert_invoke(method_text, method_name, lines, marker=None):
    """Chen cac dong smali vao dau than method (sau moi directive).

    Idempotênt theo marker. Tra (new_text, ok).
    """
    if marker and marker in method_text:
        return method_text, False
    m = find_method_block(method_text, method_name)
    if not m:
        return method_text, False
    pos = first_instruction_pos(method_text, m.start(4), m.end(4))
    block = ""
    if marker:
        block += "    " + marker + "\n"
    block += "\n".join("    " + ln if ln.strip() else ln
                       for ln in lines) + "\n"
    return method_text[:pos] + block + method_text[pos:], True


def marker_for(prefix, payload):
    """Sinh marker on dinh cho idempotêncy."""
    return "# " + prefix + ":" + hashlib.sha1(
        payload.encode("utf-8")).hexdigest()[:12]


def modern_class_kind(descriptor):
    """Nhan dien lop theo dau ra D8/R8 (truc T6):
    - R$...    : lop tai nguyen noi bo (resource inner class)
    - -$$Lambda$... : lambda duoc R8 sinh
    - Lambda$...     : lambda (dex)
    - *$...     : lop noi bo thuong
    Tra (loại, phan_mo_ta)."""
    desc = (descriptor or "").strip()
    if desc.startswith("L") and desc.endswith(";"):
        desc = desc[1:-1]
    name = desc.rsplit("/", 1)[-1]
    if name.startswith("R$") or name == "R":
        return "R-inner", name
    if "-$$Lambda$" in name or name.startswith("$$Lambda"):
        return "lambda-r8", name
    if "Lambda$" in name or "lambda$" in name:
        return "lambda", name
    if "Metadata" in name:
        return "kotlin-metadata", name
    if "$" in name:
        return "inner", name
    return "thuong", name


def kotlin_metadata_present(smali_text):
    """Kiem tra dau hieu Kotlin (metadata annotation) trong file smali."""
    return ("Lkotlin/Metadata;" in (smali_text or "")
            or "Lkotlin/jvm/internal/" in (smali_text or ""))


def unicode_safe_patch_name(name):
    """Tên patch nhieu ngon ngu (Nga/Trung/...) — giu nguyen UTF-8, chi
    chuan hoa ky tu khong an toan cho tên tệp (truc T6)."""
    import re as _re
    safe = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "")
    return safe.strip() or "patch"


# Bi danh dau gach duoi de tuong thich voi engine cu.
_smali_escape = smali_escape
_smali_quote = smali_quote
_rewrite_bool = rewrite_bool
_smali_class_descriptor = smali_class_descriptor
_smali_target_rel = smali_target_rel
_find_method_block = find_method_block
_first_instruction_pos = first_instruction_pos
_smali_alloc_temps = smali_alloc_temps
