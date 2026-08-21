# -*- coding: utf-8 -*-
"""smart_ontology — TỪ ĐIỂN HÀNH VI cho smart-scanner (giống BEHAVIORS của
ontology.py bên behavior).

Mỗi hành vi gồm: label, description, suggestions (hướng xử lý theo toolkit),
categories (ánh xạ sang danh mục phân loại của smart_scanner), keywords,
risk_base và cờ noise (nhiễu cần lọc). Hàm match_smart_behavior gán hành vi
chính + hành vi bổ trợ cho từng finding.

Chuỗi trong mã nguồn / tên file giữ nguyên gốc.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SMART_BEHAVIORS: Dict[str, Dict[str, Any]] = {
    "hardcoded_secret": {
        "label": "Khóa/bí mật nhúng cứng",
        "description": "Chuỗi giống API key, token, secret hoặc khóa riêng nằm "
                       "cố định trong .rodata/.data — dễ bị trích xuất từ APK.",
        "suggestions": [
            "Dùng `patchx rodata-patch --mode pointer` để thay bằng giá trị nạp "
            "động khi chạy (không giới hạn độ dài)",
            "Chuyển khóa sang keystore/server để không nhúng trực tiếp trong .so",
        ],
        "categories": ["api_key", "token", "secret", "private_key"],
        "keywords": ["api key", "token", "secret", "private key", "jwt",
                     "bearer", "aws", "stripe", "basic auth"],
        "risk_base": 90,
        "noise": False,
    },
    "endpoint_exposure": {
        "label": "Lộ endpoint API",
        "description": "URL/domain giao tiếp server nằm tĩnh trong nhị phân — "
                       "tiết lộ hạ tầng backend và là mục tiêu patch thường gặp.",
        "suggestions": [
            "Dùng `patchx rodata-patch --mode pointer` đổi endpoint sang domain "
            "khác khi chạy",
            "Cân nhắc mã hóa/obfuscate endpoint nếu phát hành bản production",
        ],
        "categories": ["endpoint", "domain"],
        "keywords": ["http", "https", "api", "url", "endpoint", "domain",
                     "server"],
        "risk_base": 65,
        "noise": False,
    },
    "dynamic_endpoint_build": {
        "label": "Endpoint/chuỗi ghép động",
        "description": "Nhiều chuỗi fragment/format được tham chiếu từ cùng một "
                       "hàm — nghi vấn endpoint tạo dựng từ nhiều phần nhỏ "
                       "(concat/xor/encode) không thấy được nếu chỉ tìm chuỗi tĩnh.",
        "suggestions": [
            "Dùng data-flow của smart-scan để lấy đủ chuỗi trước khi patch",
            "Hook hàm ghép chuỗi bằng Frida (frida_generator) để log giá trị "
            "runtime đầy đủ",
        ],
        "categories": ["format", "endpoint", "other"],
        "keywords": ["ghép", "concat", "format", "endpoint", "nhiều phần",
                     "dynamic", "xor", "encode"],
        "risk_base": 50,
        "noise": False,
    },
    "sensitive_header": {
        "label": "Header đặc biệt",
        "description": "Chuỗi header Authorization/X-Api-Key/Bearer — liên quan "
                       "xác thực request tới server.",
        "suggestions": [
            "Patch header bằng `rodata-patch --mode pointer` nếu cần đổi giá trị",
            "Kết hợp remote-observe để giám sát header thực tế khi app gửi request",
        ],
        "categories": ["header"],
        "keywords": ["authorization", "api-key", "bearer", "x-auth",
                     "x-access", "header"],
        "risk_base": 60,
        "noise": False,
    },
    "encoded_payload": {
        "label": "Dữ liệu mã hóa/encode",
        "description": "Chuỗi entropy cao giống mã hóa, base64/JWT hoặc có opcode "
                       "xor/encode gần tham chiếu — nội dung nhạy cảm bị che giấu.",
        "suggestions": [
            "Dùng `rodata-patch --runtime-scan` hoặc script Frida để bắt giá trị "
            "sau khi giải mã khi chạy",
            "Phân tích hàm xor/encode qua data-flow trước khi quyết định patch",
        ],
        "categories": ["cipher"],
        "keywords": ["xor", "encode", "base64", "mã hóa", "entropy", "cipher",
                     "jwt", "payload"],
        "risk_base": 75,
        "noise": False,
    },
    "jni_class_reference": {
        "label": "Tham chiếu lớp JNI",
        "description": "Descriptor tên lớp Java (com/org/android/...) dùng trong "
                       "FindClass/GetFieldID ở native.",
        "suggestions": [
            "Kết hợp `patchx targets` để biết class nào được native truy cập",
            "Hook FindClass/GetFieldID bằng Frida để log lớp đang được nạp",
        ],
        "categories": ["class"],
        "keywords": ["findclass", "jni", "class", "descriptor", "getfieldid",
                     "lớp"],
        "risk_base": 35,
        "noise": False,
    },
    "jni_flow_string": {
        "label": "Chuỗi trong luồng JNI",
        "description": "Chuỗi được tham chiếu từ hàm JNI (Java_* hoặc hàm trong "
                       "chuỗi gọi JNI) — xác thực chéo caller/callee ĐẠT.",
        "suggestions": [
            "Điểm an toàn để patch bằng `rodata-patch` (đã xác thực ngữ cảnh gọi)",
            "Dùng remote-observe để theo dõi giá trị thực tế trước khi patch",
        ],
        "categories": [],
        "keywords": ["jni", "java_", "native", "validated", "xác thực",
                     "caller", "callee"],
        "risk_base": 40,
        "noise": False,
    },
    "format_dynamic_param": {
        "label": "Chuỗi định dạng có param động",
        "description": "Chuỗi chứa %s/%d/{0}/$var — thường là template log hoặc "
                       "endpoint ghép tham số.",
        "suggestions": [
            "Phân biệt log template (nhiễu) với endpoint template (quan trọng) "
            "qua category của finding",
            "Patch template bằng `rodata-patch` nếu là endpoint động",
        ],
        "categories": ["format"],
        "keywords": ["%s", "%d", "format", "param", "template", "placeholder"],
        "risk_base": 42,
        "noise": False,
    },
    "path_exposure": {
        "label": "Đường dẫn tập tin",
        "description": "Chuỗi đường dẫn /res/, /assets/, file:... trong nhị phân "
                       "— tiết lộ cấu trúc tài nguyên.",
        "suggestions": [
            "Đối chiếu với manifest/asset nếu cần xác định tài nguyên nhạy cảm",
        ],
        "categories": ["path"],
        "keywords": ["path", "đường dẫn", "assets", "file", "res"],
        "risk_base": 30,
        "noise": False,
    },
    "log_noise": {
        "label": "Chuỗi log (nhiễu)",
        "description": "Chuỗi log/debug — bị lọc khỏi báo cáo chính bởi lọc "
                       "nhiễu ngữ nghĩa.",
        "suggestions": [
            "Chạy `--show-noise` nếu cần rà soát chuỗi log có chứa thông tin "
            "nhạy cảm",
        ],
        "categories": ["log"],
        "keywords": ["log", "debug", "info", "warn", "error", "trace"],
        "risk_base": 5,
        "noise": True,
    },
    "sample_noise": {
        "label": "Dữ liệu mẫu (nhiễu)",
        "description": "Chuỗi test/demo/example.com — dữ liệu mẫu, không phải "
                       "thông tin nhạy cảm.",
        "suggestions": [
            "Bỏ qua, hoặc dùng `--show-noise` để kiểm tra lại",
        ],
        "categories": ["sample"],
        "keywords": ["test", "demo", "example", "sample", "dummy", "lorem"],
        "risk_base": 2,
        "noise": True,
    },
    "symbol_noise": {
        "label": "Tên symbol (nhiễu)",
        "description": "Tên hàm/biến C++ mã hóa (mangled) — không phải chuỗi dữ "
                       "liệu, dùng để đối chiếu tên hàm trong data-flow.",
        "suggestions": [
            "Bỏ qua khỏi báo cáo chính; tên hàm vẫn hiển thị trong refs/functions",
        ],
        "categories": ["symbol"],
        "keywords": ["_z", "mangled", "symbol", "namespace", "c++"],
        "risk_base": 12,
        "noise": True,
    },
    "library_noise": {
        "label": "Chuỗi runtime thư viện (nhiễu)",
        "description": "Thông báo lỗi C++/thư viện hệ thống (std::, map::at, "
                       "bad_alloc...) — không liên quan logic ứng dụng.",
        "suggestions": [
            "Bỏ qua — không phải chuỗi dữ liệu của ứng dụng",
        ],
        "categories": ["library"],
        "keywords": ["std", "bad_alloc", "map::at", "exception", "runtime"],
        "risk_base": 8,
        "noise": True,
    },
    "signature_verify_gate": {
        "label": "Xác minh chữ ký chặn đăng ký natives",
        "description": "Lib đọc base.apk của chính nó (openat) + /proc/self/maps; "
                       "khi chữ ký APK lệch bản gốc, JNI_OnLoad vẫn trả "
                       "JNI_VERSION_1_6 (0x10006) nhưng BỎ QUA RegisterNatives -> "
                       "app crash UnsatisfiedLinkError: No implementation found. "
                       "Điểm quyết định nằm TRƯỚC đăng ký natives, không phải abort.",
        "suggestions": [
            "Tìm nhánh quyết định trong JNI_OnLoad (rẽ nhánh trước RegisterNatives) "
            "rồi patch ép luôn đăng ký",
            "Hoặc thay hash chứng chỉ nhúng trong .rodata/.data bằng hash chứng chỉ "
            "mới của keystore re-sign",
            "Kiểm chứng luồng bằng `patchx remote-observe` (quan sát openat base.apk "
            "và RegisterNatives)",
        ],
        "categories": ["signature", "integrity", "tamper"],
        "keywords": ["base.apk", "signature", "tamper", "verify", "integrity",
                     "JNI_OnLoad", "RegisterNatives", "chữ ký"],
        "risk_base": 95,
        "noise": False,
    },
    "jni_onload_stealth_fail": {
        "label": "JNI_OnLoad thất bại ngầm",
        "description": "JNI_OnLoad trả version hợp lệ (0x10006) nhưng không đăng ký "
                       "natives khi xác minh thất bại — phản ứng tamper ngầm, không "
                       "abort, khó thấy bằng logcat thông thường.",
        "suggestions": [
            "So sánh luồng RegisterNatives giữa bản gốc và bản patch bằng "
            "remote-observe để xác định điểm rẽ nhánh",
            "Hook vtable JNIEnv index 215 + symbol nội bộ ART "
            "(ClassLinker::RegisterNative) để bắt đăng ký thật",
        ],
        "categories": ["tamper", "native", "integrity"],
        "keywords": ["JNI_OnLoad", "0x10006", "JNI_VERSION_1_6", "RegisterNatives",
                     "bỏ qua", "stealth"],
        "risk_base": 90,
        "noise": False,
    },
    "native_register_art_internal": {
        "label": "Đăng ký natives qua ART nội bộ",
        "description": "Không gọi JNIEnv->RegisterNatives (vtable index 215) — dùng "
                       "API nội bộ ART (ClassLinker::RegisterNative / "
                       "RuntimeCallbacks) để né hook vtable của Frida thông thường.",
        "suggestions": [
            "Hook symbol _ZN3art11ClassLinker14RegisterNativeEPNS_6ThreadEPNS_9ArtMethodEPKv "
            "trong libart.so khi quan sát runtime",
            "Khi patch tĩnh: tìm lệnh ldr/blr đọc vtable JNIEnv hoặc lời gọi "
            "trực tiếp tới symbol ART",
        ],
        "categories": ["native", "shell", "integrity"],
        "keywords": ["ClassLinker", "RegisterNative", "libart", "JNIEnv", "vtable",
                     "RuntimeCallbacks"],
        "risk_base": 85,
        "noise": False,
    },
    "abort_plt_many_sites": {
        "label": "Nhiều điểm kill qua abort",
        "description": "Lib có rất nhiều call-site abort (ví dụ 378 trong "
                       "libmtprotect.so) — mọi nhánh fail đều chảy qua PLT abort. "
                       "Patch PLT abort->ret giữ natives nhưng KHÔNG đủ nếu quyết "
                       "định nằm trước RegisterNatives.",
        "suggestions": [
            "Patch PLT abort->ret (0xd65f03c0) để vô hiệu các nhánh kill, "
            "kết hợp patch điểm quyết định xác minh",
            "Ưu tiên tìm điểm quyết định chính trước (xem signature_verify_gate)",
        ],
        "categories": ["integrity", "tamper"],
        "keywords": ["abort", "plt", "kill", "call-site", "điểm quyết định"],
        "risk_base": 70,
        "noise": False,
    },
    "reads_own_apk_integrity": {
        "label": "Đọc base.apk tự xác minh",
        "description": "Lib mở và đọc file base.apk của chính ứng dụng để xác minh "
                       "toàn vẹn/chữ ký (openat + read) — dấu hiệu shell bảo vệ "
                       "(Legu/MT Protect).",
        "suggestions": [
            "Dùng remote-observe hook __openat_2/read để log đường dẫn lib đọc",
            "Phân tích vùng nhớ sau khi đọc để tìm thao tác so khớp chữ ký",
        ],
        "categories": ["integrity", "signature"],
        "keywords": ["base.apk", "openat", "read", "verify", "toàn vẹn"],
        "risk_base": 80,
        "noise": False,
    },
    "reads_proc_self_maps": {
        "label": "Đọc /proc/self/maps",
        "description": "Lib đọc /proc/self/maps của chính tiến trình — dò hook "
                       "(Frida/LSPosed) hoặc anti-debug phổ biến trong shell bảo vệ.",
        "suggestions": [
            "Hook __openat_2 để log; chặn open /proc/self/maps nếu cần né dò hook",
            "Kết hợp fake ro.debuggable=0 qua __system_property_get",
        ],
        "categories": ["antidebug", "integrity"],
        "keywords": ["/proc/self/maps", "maps", "anti-debug", "ptrace", "frida"],
        "risk_base": 75,
        "noise": False,
    },
    "jni_payload_activation": {
        "label": "JNI payload kích hoạt có điều kiện",
        "description": "Các natives của lớp shell (vd l.*.<clinit>) chỉ được đăng ký "
                       "khi xác minh toàn vẹn ĐẠT — payload JNI kích hoạt có điều "
                       "kiện; stub sạch thiếu natives này sẽ crash ngay khi lớp shell "
                       "được nạp.",
        "suggestions": [
            "Không thay bằng stub sạch khi lib chứa natives thật của app — phải "
            "patch bản lib gốc",
            "Dump danh sách natives bằng remote-observe (hook RegisterNatives/ART) "
            "trước khi quyết định stub",
        ],
        "categories": ["shell", "native", "tamper"],
        "keywords": ["payload", "JNI", "clinit", "shell", "natives", "l.",
                     "RegisterNatives"],
        "risk_base": 88,
        "noise": False,
    },
    "other_behavior": {
        "label": "Chuỗi khác",
        "description": "Chuỗi chưa khớp hành vi cụ thể — xem bằng chứng để đánh "
                       "giá thêm.",
        "suggestions": [
            "Chạy lại với `--show-noise` hoặc `--min-risk` thấp hơn để so sánh",
        ],
        "categories": ["other"],
        "keywords": [],
        "risk_base": 30,
        "noise": False,
    },
}


def all_behaviors() -> Dict[str, Dict[str, Any]]:
    """Từ điển gốc + hành vi TỰ PHÁT HIỆN (kho behavior_learner) — dùng chung
    cho MỌI module smart_scan để nhận diện hành vi mới ngay lần quét sau."""
    try:
        from .behavior_learner import all_behaviors as _merged
        return _merged()
    except Exception:
        return dict(SMART_BEHAVIORS)


def get_behavior(behavior_id: str) -> Dict[str, Any]:
    """Lấy entry từ điển hành vi (kể cả hành vi tự phát hiện); mặc định
    other_behavior nếu thiếu."""
    if behavior_id in SMART_BEHAVIORS:
        out = dict(SMART_BEHAVIORS[behavior_id])
        out["id"] = behavior_id
        return out
    discovered = all_behaviors().get(behavior_id)
    if discovered:
        out = dict(discovered)
        out["id"] = behavior_id
        return out
    out = dict(SMART_BEHAVIORS["other_behavior"])
    out["id"] = "other_behavior"
    return out


CATEGORY_BEHAVIOR: Dict[str, str] = {
    "api_key": "hardcoded_secret",
    "token": "hardcoded_secret",
    "secret": "hardcoded_secret",
    "private_key": "hardcoded_secret",
    "endpoint": "endpoint_exposure",
    "domain": "endpoint_exposure",
    "header": "sensitive_header",
    "cipher": "encoded_payload",
    "class": "jni_class_reference",
    "format": "format_dynamic_param",
    "path": "path_exposure",
    "log": "log_noise",
    "sample": "sample_noise",
    "symbol": "symbol_noise",
    "library": "library_noise",
    "other": "other_behavior",
    "signature": "signature_verify_gate",
    "integrity": "signature_verify_gate",
    "tamper": "signature_verify_gate",
    "antidebug": "reads_proc_self_maps",
    "native": "native_register_art_internal",
    "shell": "jni_payload_activation",
}


def match_smart_behavior(
    category: str,
    validated: bool = False,
    dynamic_build: bool = False,
) -> Tuple[str, List[str]]:
    """Gán hành vi CHÍNH theo category + hành vi BỔ TRỢ (jni_flow_string khi
    xác thực chéo đạt; dynamic_endpoint_build khi nghi vấn ghép động)."""
    primary = CATEGORY_BEHAVIOR.get(category, "other_behavior")
    extra: List[str] = []
    if validated and primary not in ("log_noise", "sample_noise",
                                     "symbol_noise", "library_noise"):
        extra.append("jni_flow_string")
    if dynamic_build and category in ("endpoint", "format", "other"):
        extra.append("dynamic_endpoint_build")
    return primary, extra


def render_behavior_catalog() -> str:
    """In toàn bộ từ điển hành vi (giống ontology.py) để tra cứu nhanh."""
    lines = [
        "TỪ ĐIỂN HÀNH VI — smart-scanner (smart_ontology.py)",
        "=" * 70,
    ]
    for bid, b in all_behaviors().items():
        discovered = bool(b.get("discovered"))
        lines.append("")
        lines.append("%s — %s%s%s" % (bid, b["label"],
                                      "  [NHIỄU]" if b.get("noise") else "",
                                      "  [TỰ PHÁT HIỆN]" if discovered else ""))
        lines.append("  Mô tả: %s" % b.get("description", ""))
        lines.append("  Danh mục: %s"
                     % ", ".join(b.get("categories") or ["(mọi)"]))
        lines.append("  Risk nền: %d | Từ khóa: %s"
                     % (b.get("risk_base", 30),
                        ", ".join(b.get("keywords") or []) or "(không)"))
        for s in b.get("suggestions", []):
            lines.append("  - %s" % s)
    return "\n".join(lines)


def behavior_catalog_ids() -> List[str]:
    return list(SMART_BEHAVIORS.keys())
