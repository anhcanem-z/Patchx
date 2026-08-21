# -*- coding: utf-8 -*-
"""Các luồng thực thi theo bộ chức năng hành vi.

Mỗi luồng gom một nhóm behavior trong ontology và chạy đúng chuỗi:
smali -> detector -> cfg -> behavior -> evidence -> target -> rank -> review -> thực thi.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from .ontology import BEHAVIORS


FLOW_GROUPS: Dict[str, Dict[str, Any]] = {
    "integrity": {
        "title": "Luồng kiểm tra toàn vẹn và chống giả mạo",
        "description": "Gom bằng chứng về chữ ký, DEX, APK, debugger, emulator, root, Frida, Xposed.",
        "behaviors": [
            "integrity_check",
            "debug_detection",
            "emulator_detection",
            "anti_frida",
            "anti_hook",
            "root_detection",
            "tamper_detection",
            "time_based_check",
            "native_library_check",
        ],
    },
    "authentication": {
        "title": "Luồng đăng nhập và phiên đăng nhập",
        "description": "Phát hiện login, sign-in, token, session, xác thực tài khoản và kiểm tra trạng thái đã đăng nhập.",
        "behaviors": [
            "login_authentication",
            "api_server_flow",
            "remote_configuration",
            "keystore_key_usage",
            "cryptographic_operations",
        ],
    },
    "monetization": {
        "title": "Luồng thanh toán và tài khoản trả phí",
        "description": "Tập trung Pro/Premium/VIP, Google Play Billing, cấu hình từ máy chủ.",
        "behaviors": [
            "pro_premium_check",
            "google_billing",
            "api_server_flow",
            "manifest_res_check",
            "remote_configuration",
        ],
    },
    "network_ssl": {
        "title": "Luồng mạng và SSL Pinning",
        "description": "Phát hiện HTTP/HTTPS, TrustManager, HostnameVerifier, CertificatePinner.",
        "behaviors": [
            "api_server_flow",
            "ssl_pinning",
            "remote_configuration",
        ],
    },
    "privacy_security": {
        "title": "Luồng quyền riêng tư và dữ liệu nhạy cảm",
        "description": "Gom quyền Android, vị trí, log, clipboard, màn hình, Keystore, mã hoá và backup.",
        "behaviors": [
            "permission_usage",
            "location_usage",
            "logging_usage",
            "clipboard_monitoring",
            "screen_capture_detection",
            "keystore_key_usage",
            "cryptographic_operations",
            "backup_restore_check",
        ],
    },
    "dynamic_code": {
        "title": "Luồng mã động và phản chiếu",
        "description": "Phát hiện DexClassLoader, reflection, WebView bridge và nạp mã lúc chạy.",
        "behaviors": [
            "dynamic_code_loading",
            "reflection_usage",
            "webview_js_bridge",
        ],
    },
    "environment": {
        "title": "Luồng phụ thuộc môi trường",
        "description": "Gom kiểm tra Google Play Services, root, Magisk, Frida, Xposed và cấu hình máy chủ.",
        "behaviors": [
            "dependency_check",
            "remote_configuration",
            "anti_frida",
            "anti_hook",
            "root_detection",
        ],
    },
    "all": {
        "title": "Luồng tổng hợp toàn bộ hành vi",
        "description": "Chạy tất cả behavior trong ontology, không lọc.",
        "behaviors": sorted(BEHAVIORS),
    },
}


def available_flows() -> list[str]:
    """Danh sách tên luồng, sắp theo thứ tự khai báo."""
    return list(FLOW_GROUPS)


def get_flow_definition(flow_name: str) -> Dict[str, Any]:
    """Lấy định nghĩa luồng hoặc trả rỗng nếu không tồn tại."""
    key = normalize_flow_name(flow_name)
    return FLOW_GROUPS.get(key, {})


def normalize_flow_name(flow_name: str) -> str:
    """Chuẩn hoá tên luồng sang key ASCII, bỏ dấu nếu người dùng gõ tiếng Việt."""
    text = str(flow_name or "").strip().lower()
    aliases = {
        "all": "all",
        "tat ca": "all",
        "toan bo": "all",
        "toàn bộ": "all",
        "integrity": "integrity",
        "toan ven": "integrity",
        "toàn vẹn": "integrity",
        "authentication": "authentication",
        "login": "authentication",
        "dang nhap": "authentication",
        "đăng nhập": "authentication",
        "dang nhap va phien": "authentication",
        "đăng nhập và phiên": "authentication",
        "monetization": "monetization",
        "thanh toan": "monetization",
        "thanh toán": "monetization",
        "network_ssl": "network_ssl",
        "ssl": "network_ssl",
        "mang": "network_ssl",
        "mạng": "network_ssl",
        "privacy_security": "privacy_security",
        "quyen rieng tu": "privacy_security",
        "quyền riêng tư": "privacy_security",
        "dynamic_code": "dynamic_code",
        "ma dong": "dynamic_code",
        "mã động": "dynamic_code",
        "environment": "environment",
        "moi truong": "environment",
        "môi trường": "environment",
    }
    return aliases.get(text, text)


def filter_behaviors(behaviors: Iterable[Any], flow_name: str) -> list[Any]:
    """Lọc danh sách behavior theo một luồng đã định nghĩa."""
    definition = get_flow_definition(flow_name)
    allowed = set(definition.get("behaviors", []))
    if not allowed:
        return list(behaviors)
    return [behavior for behavior in behaviors if behavior.name in allowed]



def flow_alias_for_behavior(behavior_name: str) -> str:
    """Tra cứu tên luồng hiển thị cho một behavior, dùng khi in gợi ý cho người dùng."""
    for key, definition in FLOW_GROUPS.items():
        if key == "all":
            continue
        if behavior_name in definition.get("behaviors", []):
            return definition.get("title", key)
    return "Khác"


__all__ = [
    "FLOW_GROUPS",
    "available_flows",
    "get_flow_definition",
    "normalize_flow_name",
    "filter_behaviors",
    "flow_alias_for_behavior",
]
