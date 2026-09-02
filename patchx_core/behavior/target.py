from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


def _clean_frida_class(value: str) -> str:
    """Chuan hoa class tu Smali/Path sang dang Frida/Java."""
    c = (value or "").strip()
    if c.startswith("L") and c.endswith(";"):
        c = c[1:-1]
    c = c.replace("/", ".").replace("\\", ".")
    if c.endswith(".smali"):
        c = c[:-6]
    return c


def _frida_method_access(method: str) -> str:
    """Tao truy cap method an toan cho Frida (dung bracket notation)."""
    method = (method or "").strip()
    if not method:
        return "clazz"
    return f"clazz[{json.dumps(method)}]"


def target_evidence_score(target: "Target") -> float:
    """Cham điểm target theo do manh cua bang chung."""
    evidence = target.evidence or []
    if not evidence:
        return 0.0

    weights = [float(item.get("weight", 0.0)) for item in evidence]
    has_cfg = any(
        str(item.get("kind", "")) == "cfg-branch-analysis"
        for item in evidence
    )

    mean_weight = sum(weights) / len(weights)
    count_bonus = min(len(evidence), 5) * 0.08
    cfg_bonus = 0.12 if has_cfg else 0.0

    score = (
        target.confidence * 0.55
        + mean_weight * 0.25
        + count_bonus
        + cfg_bonus
    )
    return round(min(max(score, 0.0), 1.0), 4)


BYPASS_PRIORITY = {
    "xac minh pro/premium": 1.00,
    "xac thuc dang nhap": 0.98,
    "kiem tra ssl certificate": 0.96,
    "thanh toan google play": 0.94,
    "xac minh toan ven": 0.90,
    "xac minh manifest & resource": 0.82,
    "luong goi api server": 0.80,
    "kiem tra thoi gian / het han": 0.70,
    "phat hien root / su": 0.60,
    "chong hook / xposed": 0.58,
    "phat hien may ao / emulator": 0.55,
    "chong frida": 0.50,
    "ma hoa / giai ma": 0.45,
    "dung reflection": 0.42,
    "nap ma dong": 0.40,
}


def target_bypass_score(target: "Target") -> float:
    """Diem uu tien kha nang bypass dung diem."""
    base = target_evidence_score(target)
    hookable_bonus = 0.10 if target.is_frida_hookable() else 0.0
    method_bonus = 0.05 if target.method and target.class_name else 0.0
    priority = BYPASS_PRIORITY.get(target.category, 0.35)

    score = (
        base * 0.75
        + priority * 0.15
        + hookable_bonus
        + method_bonus
    )
    return round(min(max(score, 0.0), 1.0), 4)


@dataclass
class Target:
    """
    Mot điểm mức tieu can nguoi phan tich xem xet.
    Chua thông tin vi tri va cac phuong an goi y de can thiep.
    """

    category: str
    confidence: float

    source: str = ""
    method: str = ""
    class_name: str = ""

    line: int | None = None
    reason: str = ""

    evidence: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    # Cac phuong an goi y can thiep (duyet tay & tu dong)
    suggested_actions: dict[str, Any] = field(default_factory=dict)

    def _clean_class_name(self) -> str:
        """Lam sach tên class tu dang Smali/Path (Lcom/app/Class;) sang dang Java chuan cho Frida (com.app.Class)."""
        c = self.class_name.strip()
        if c.startswith("L") and c.endswith(";"):
            c = c[1:-1]
        c = c.replace("/", ".").replace("\\", ".")
        if c.endswith(".smali"):
            c = c[:-6]
        return c

    @property
    def stable_id(self) -> str:
        clean_class = self._clean_class_name()
        method = self.method or "unknown"
        return (
            f"{self.category}:{clean_class}->{method}"
            .replace(".", "_")
            .replace("$", "_")
        )

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @property
    def has_cfg_evidence(self) -> bool:
        return any(
            str(item.get("kind", "")) == "cfg-branch-analysis"
            for item in self.evidence
        )

    def location_dict(self) -> dict[str, Any]:
        """Vi tri thuc thi chi tiet: source, class, method, line, api/branch."""
        details = self.details or {}
        return {
            "source_file": self.source,
            "class": self._clean_class_name(),
            "method": self.method,
            "line": self.line,
            "api_line": details.get("api_line"),
            "branch_line": details.get("branch_line"),
            "api_instruction": details.get("api"),
            "branch_instruction": details.get("branch"),
        }

    def is_frida_hookable(self) -> bool:
        """Frida chi can identity class+method de tao hook; khong can cac truong khac."""
        return bool(self._clean_class_name() and self.method)

    def to_review_dict(self) -> dict[str, Any]:
        return {
            "id": self.stable_id,
            "category": self.category,
            "confidence": self.confidence,
            "evidence_score": target_evidence_score(self),
            "bypass_score": target_bypass_score(self),
            "location": self.location_dict(),
            "source": self.source,
            "class": self.class_name,
            "method": self.method,
            "line": self.line,
            "reason": self.reason,
            "evidence_count": self.evidence_count,
            "cfg_backed": self.has_cfg_evidence,
            "frida_hookable": self.is_frida_hookable(),
            "suggestions": self.suggested_actions.get("user_options", []),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "class": self.class_name,
            "method": self.method,
            "line": self.line,
            "reason": self.reason,
            "evidence": self.evidence,
            "details": self.details,
            "suggested_actions": self.suggested_actions,
        }

    def to_frida_hook_config(self) -> dict[str, Any]:
        """Chuyen doi Target thanh cau hinh chuan de Frida JS Agent nap truc tiep."""
        clean_class = self._clean_class_name()
        auto_strat = self.suggested_actions.get("auto_strategy", {})

        action_type = auto_strat.get("action_type", "generic_observe")
        patch_mode = auto_strat.get("patch_mode", "log_call")
        method_access = _frida_method_access(self.method)
        method_literal = json.dumps(self.method or "")
        override_value = auto_strat.get("override_value", None)
        mock_fields = auto_strat.get("mock_fields", {})
        smali_code = auto_strat.get("smali_patch_code", "")

        frida_script = auto_strat.get("frida_hook_script")
        if not frida_script:
            if action_type == "smali_return_override" and override_value is not None:
                frida_script = (
                    f"Java.perform(function() {{\n"
                    f"    try {{\n"
                    f"        var clazz = Java.use('{clean_class}');\n"
                    f"        {method_access}.implementation = function() {{\n"
                    f"            console.log('[+] [Frida Bypass] Forced return {override_value} on {clean_class}.{self.method}');\n"
                    f"            return {str(override_value).lower()};\n"
                    f"        }};\n"
                    f"    }} catch(e) {{\n"
                    f"        console.error('[-] Error hooking {clean_class}.{self.method}: ' + e.message);\n"
                    f"    }}\n"
                    f"}});"
                )
            else:
                frida_script = (
                    f"Java.perform(function() {{\n"
                    f"    try {{\n"
                    f"        var clazz = Java.use('{clean_class}');\n"
                    f"        {method_access}.implementation = function() {{\n"
                    f"            console.log('[*] [Frida Trace] Called {clean_class}.{self.method}');\n"
                    f"            return this[{method_literal}].apply(this, arguments);\n"
                    f"        }};\n"
                    f"    }} catch(e) {{\n"
                    f"        console.error('[-] Error tracing {clean_class}.{self.method}: ' + e.message);\n"
                    f"    }}\n"
                    f"}});"
                )

        rule_id = f"rule_{clean_class}_{self.method}".replace(".", "_").replace("$", "_")
        location = self.location_dict()
        location["class"] = clean_class

        return {
            "id": rule_id,
            "enabled": True,
            "category": self.category,
            "confidence": self.confidence,
            "target": location,
            "action": {
                "type": action_type,
                "patch_mode": patch_mode,
                "override_value": override_value,
                "mock_fields": mock_fields,
                "smali_patch_code": smali_code,
            },
            "frida_script": frida_script,
            "meta": {
                "reason": self.reason,
                "evidence_count": len(self.evidence),
            },
        }


class TargetAnalyzer:
    """
    Phan tich Behavior/Evidence, nhan dien cac điểm Pro/Premium, Google Billing, SSL,
    API Server, Manifest/Resource va dua ra phuong an thay doi hanh vi tu dong (Smali + Frida JSON).
    """

    CATEGORY_MAP = {
        "integrity_check": "xac minh toan ven",
        "debug_detection": "phat hien go lỗi",
        "permission_usage": "quyen",
        "logging_usage": "ghi nhat ky",
        "remote_configuration": "cau hinh tu may chu",
        "location_usage": "vi tri",
        "dependency_check": "kiem tra phu thuoc & moi truong",
        # Hang mức Pro, Payment & Security
        "pro_premium_check": "xac minh pro/premium",
        "login_authentication": "xac thuc dang nhap",
        "google_billing": "thanh toan google play",
        "ssl_pinning": "kiem tra ssl certificate",
        "api_server_flow": "luong goi api server",
        "manifest_res_check": "xac minh manifest & resource",
        "emulator_detection": "phat hien may ao / emulator",
        "anti_frida": "chong frida",
        "anti_hook": "chong hook / xposed",
        "root_detection": "phat hien root / su",
        "tamper_detection": "phat hien apk bi chinh sua",
        "time_based_check": "kiem tra thoi gian / het han",
        "dynamic_code_loading": "nap ma dong",
        "reflection_usage": "dung reflection",
        "native_library_check": "kiem tra native library",
        "webview_js_bridge": "bridge webview / javascript",
        "clipboard_monitoring": "giam sat clipboard",
        "screen_capture_detection": "chong chup man hinh",
        "keystore_key_usage": "dung android keystore",
        "backup_restore_check": "kiem tra backup / restore",
        "cryptographic_operations": "ma hoa / giai ma",
    }

    def __init__(self, root):
        self.root = Path(root)

    @staticmethod
    def _parse_method_name(method_text: str) -> str:
        """Chuan hoa `.method public isPro()Z` thanh `isPro`."""
        text = (method_text or "").strip()
        if not text:
            return ""

        text = re.sub(r"^\.method\s+", "", text)
        match = re.search(r"\b([A-Za-z_$][\w$]*)\s*\(", text)
        if match:
            return match.group(1)

        return text.split()[-1] if text else ""

    # =====================================================
    # CONG KHAI
    # =====================================================

    def analyze(self, behaviors) -> list[Target]:
        targets = []

        for behavior in behaviors:
            category = self.CATEGORY_MAP.get(
                behavior.name,
                behavior.name,
            )

            for evidence in behavior.evidence:
                target = self._make_target(
                    category,
                    behavior,
                    evidence,
                )

                if target is not None:
                    targets.append(target)

        return self._merge_targets(targets)

    def rank_targets(
        self,
        targets: list[Target],
        min_score: float = 0.65,
        top_k: int | None = 150,
    ) -> list[Target]:
        """Chi giu cac target co kha nang bypass cao, sap theo diem uu tien."""
        scored = sorted(
            targets,
            key=lambda item: (
                -target_bypass_score(item),
                -target_evidence_score(item),
                -item.confidence,
                -item.evidence_count,
            ),
        )

        selected: list[Target] = []
        for target in scored:
            if top_k is not None and len(selected) >= top_k:
                break
            if target_bypass_score(target) < min_score:
                continue
            selected.append(target)

        return selected

    # =====================================================
    # TAO MUC TIEU
    # =====================================================

    def _make_target(
        self,
        category: str,
        behavior,
        evidence,
    ) -> Target | None:

        details = dict(evidence.details or {})
        source = evidence.source or ""

        method = self._parse_method_name(str(details.get("method", "")))
        class_name = str(details.get("class", ""))

        # Trich xuat class_name tu nguon file Smali neu chua co
        if not class_name and source.endswith(".smali"):
            normalized = source.replace("\\", "/")
            match = re.search(r"(?:^|/)smali(?:_classes\d+)?/(.+?)(?=\.smali$)", normalized)
            if match:
                class_name = match.group(1).replace("/", ".")
            else:
                class_name = ""
        elif not class_name:
            class_name = ""

        class_name = _clean_frida_class(class_name)

        line = details.get("line")
        if line is None:
            line = details.get("branch_line")
        if line is None:
            line = details.get("api_line")

        reason = self._reason(
            category,
            evidence.kind,
            evidence.value,
        )

        suggested_actions = self._suggest_actions(
            category=category,
            kind=evidence.kind,
            value=evidence.value,
            class_name=class_name,
            method=method,
            details=details,
        )

        patch_mode = suggested_actions.get("auto_strategy", {}).get("patch_mode")
        if patch_mode in {
            "force_boolean_true",
            "nop_method_or_hook",
            "billing_response_ok",
            "force_login_success",
            "fake_logged_in",
            "skip_login_gate",
        } and (not method or not class_name):
            return None

        return Target(
            category=category,
            confidence=self._confidence(
                behavior.confidence,
                evidence.weight,
            ),
            source=source,
            method=method,
            class_name=class_name,
            line=line,
            reason=reason,
            evidence=[
                {
                    "kind": evidence.kind,
                    "value": evidence.value,
                    "weight": evidence.weight,
                }
            ],
            details=details,
            suggested_actions=suggested_actions,
        )

    # =====================================================
    # GIAI THICH
    # =====================================================

    def _reason(
        self,
        category: str,
        kind: str,
        value: str,
    ) -> str:

        if category == "xac minh toan ven" and kind == "cfg-branch-analysis":
            return "Phat hien API lien quan den xac minh toan ven va ket qua cua luong co the dieu khien mot nhanh CFG."

        if category == "xac minh toan ven":
            return "Phat hien thanh phan thuong xuat hien trong qua trinh kiem tra chu ky hoac toan ven cua ung dung."

        if category == "phat hien go lỗi":
            return "Phat hien API hoac logic co kha nang kiem tra trang thai go lỗi."

        if category == "quyen":
            if kind == "permission-request":
                return "Phat hien điểm ung dung yeu cau quyen tu he dieu hanh."
            if kind == "permission-check":
                return "Phat hien điểm ung dung kiem tra trang thai cua quyen."
            return "Phat hien quyen duoc khai bao trong ung dung."

        if category == "ghi nhat ky":
            return "Phat hien lỗi goi Android Log trong ma Smali."

        if category == "cau hinh tu may chu":
            return "Phat hien thanh phan lien quan den giao tiep mang."

        if category == "vi tri":
            return "Phat hien API hoac quyen lien quan den vi tri thiet bi."

        if category == "xac minh pro/premium":
            return "Phat hien luong kiem tra trang thai mua hang, goi Pro/VIP hoac co kiem tra ban quyen ung dung."

        if category == "thanh toan google play":
            return "Phat hien thu vien Google Play Billing v3-v6+ (com.android.billingclient) dung de thanh toan In-App."

        if category == "kiem tra ssl certificate":
            return "Phat hien ma nguon thiet lap SSL Pinning, TrustManager hoac xac minh chung chi SSL de chan Proxy/Mitm."

        if category == "luong goi api server":
            return "Phat hien API endpoint, cau hinh HTTP Request/Response, hoac bo chuyen doi du lieu trao doi voi Server."

        if category == "xac minh manifest & resource":
            return "Phat hien truy van AndroidManifest meta-data hoac doc co tai nguyen (Resources boolean) de xac minh tinh nang."

        if category == "xac thuc dang nhap":
            if kind == "login_session_state_check":
                return "Phat hien ham kiem tra trang thai da dang nhap; co the gia lap true de bo qua man hinh dang nhap."
            if kind == "login_login_gate":
                return "Phat hien dieu kien bat buoc dang nhap; co the vo hieu hoa luong chuyen den man hinh Login."
            if kind == "login_login_execute":
                return "Phat hien ham thuc hien xac thuc dang nhap; co the ep tra ve ket qua thanh cong."
            if kind == "cfg-branch-analysis":
                return "Phat hien nhanh dieu kien trong luong dang nhap/xac thuc phien."
            return "Phat hien thanh phan dang nhap, token hoac kiem tra phien nguoi dung."

        return f"Phat hien bang chung {kind}: {value}"

    # =====================================================
    # GOI Y PHUONG AN CAN THIEP & TU DONG BYPASS
    # =====================================================

    def _suggest_actions(
        self,
        category: str,
        kind: str,
        value: str,
        class_name: str,
        method: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Xay dung tap goi y hanh dong cho nguoi dung chon hoac tu dong bypass bang Smali / Frida.
        """
        user_options = []
        auto_strategy = {}
        method_access = _frida_method_access(method)
        method_literal = json.dumps(method or "")

        if category == "xac minh pro/premium":
            user_options = [
                f"Sua gia tri tra ve cua phuong thuc '{method}' thanh true (0x1) trong Smali.",
                "Dao nguoc nhanh re dieu kien (if-eqz -> if-nez / goto) tai lệnh kiem tra ban quyen.",
                f"Hook phuong thuc '{class_name}->{method}' bang Frida ep tra ve true.",
            ]
            auto_strategy = {
                "action_type": "smali_return_override",
                "target_class": class_name,
                "target_method": method,
                "override_value": True,
                "patch_mode": "force_boolean_true",
                "smali_patch_code": ".method public isPro()Z\n    .registers 1\n    const/4 v0, 0x1\n    return v0\n.end method",
                "frida_hook_script": (
                    "Java.perform(function() {\n"
                    "    try {\n"
                    f"        var clazz = Java.use('{class_name}');\n"
                    f"        {method_access}.implementation = function() {{\n"
                    f"            console.log('[+] Bypassed Pro Check: {class_name}.{method} -> true');\n"
                    "            return true;\n"
                    "        };\n"
                    "    } catch (e) { console.error('[-] Error: ' + e.message); }\n"
                    "});"
                ),
            }

        elif category == "thanh toan google play":
            user_options = [
                "Patch `getPurchaseState()` tra ve 0 (PURCHASED).",
                "Override callback `onPurchasesUpdated()` luon chuyen `BillingResult.getResponseCode()` ve OK (0).",
                "Hook `BillingClient.isReady()` va `queryPurchasesAsync()` tra ve danh sach goi da mua thanh cong.",
            ]
            auto_strategy = {
                "action_type": "bypass_google_billing",
                "target_class": class_name,
                "target_method": method,
                "patch_mode": "billing_response_ok",
                "smali_patch_code": "const/4 v0, 0x0\nreturn v0 # BillingResponseCode.OK",
                "frida_hook_script": (
                    "Java.perform(function() {\n"
                    "    try {\n"
                    "        var BillingResult = Java.use('com.android.billingclient.api.BillingResult');\n"
                    "        BillingResult.getResponseCode.implementation = function() {\n"
                    "            console.log('[+] Google Billing response forced to OK (0)');\n"
                    "            return 0;\n"
                    "        };\n"
                    "    } catch (e) { console.error(e.message); }\n"
                    "});"
                ),
            }

        elif category == "kiem tra ssl certificate":
            user_options = [
                "Nop (Xoa bo noi dung) phuong thuc checkServerTrusted trong TrustManager.",
                "Hook CertificatePinner.check() cua OkHttp de bo qua kiem tra pin.",
                "Them network_security_config.xml vao APK cho phep tin tuong chung chi nguoi dung.",
            ]
            auto_strategy = {
                "action_type": "bypass_ssl_pinning",
                "target_class": class_name,
                "target_method": method,
                "patch_mode": "nop_method_or_hook",
                "smali_patch_code": ".method public checkServerTrusted([Ljava/security/cert/X509Certificate;Ljava/lang/String;)V\n    .registers 3\n    return-void\n.end method",
                "frida_hook_script": (
                    "Java.perform(function() {\n"
                    "    try {\n"
                    "        var TrustManager = Java.use('javax.net.ssl.X509TrustManager');\n"
                    "        console.log('[+] Generic SSL Pinning Bypass injected');\n"
                    "    } catch (e) { console.error(e.message); }\n"
                    "});"
                ),
            }

        elif category == "luong goi api server":
            user_options = [
                "Hook OkHttp Interceptor de trao du lieu JSON tra ve (Sua is_pro=true, status=active).",
                "Thay doi Base URL sang Server Mock ca nhan de kiem soat hoan toan API.",
                "Ghi de Header Authentication/Bearer Token trong Request.",
            ]
            auto_strategy = {
                "action_type": "api_interceptor_hook",
                "target_endpoint": value,
                "patch_mode": "json_response_rewrite",
                "mock_fields": {
                    "is_pro": True,
                    "is_premium": True,
                    "license": "valid",
                },
            }

        elif category == "xac minh manifest & resource":
            user_options = [
                "Sua file AndroidManifest.xml: Them/Sua the <meta-data> cap quyen Premium.",
                "Sua file res/values/bools.xml: Doi gia tri ID tai nguyen Pro sang 'true'.",
                "Hook android.content.res.Resources.getBoolean() ep tra ve true khi gap ID tuong ung.",
            ]
            auto_strategy = {
                "action_type": "res_manifest_patch",
                "target_key": value,
                "patch_mode": "manifest_xml_inject_or_res_override",
            }

        elif category == "xac thuc dang nhap":
            method_kind = details.get("method_kind") or "login-execute"
            return_type = details.get("return_type") or "Z"

            if return_type == "V":
                forced_return = "            return;\n"
                original_return = (
                    f"            this[{method_literal}].apply(this, arguments);\n"
                    "            return;\n"
                )
            elif return_type.startswith("L"):
                forced_return = (
                    f"            return this[{method_literal}].apply(this, arguments);\n"
                )
                original_return = forced_return
            else:
                forced_return = "            return true;\n"
                original_return = (
                    f"            return this[{method_literal}].apply(this, arguments);\n"
                )

            if method_kind == "session-state-check":
                user_options = [
                    f"Patch `{class_name}->{method}()` tra ve true de gia lap da dang nhap.",
                    f"Hook `{class_name}.{method}` bang Frida va luon tra ve true.",
                    "Kiem tra SharedPreferences/token/session gan do de chon key phu hop.",
                ]
                auto_strategy = {
                    "action_type": "fake_logged_in",
                    "target_class": class_name,
                    "target_method": method,
                    "override_value": True,
                    "patch_mode": "fake_logged_in",
                    "method_kind": method_kind,
                    "return_type": return_type,
                    "frida_hook_script": (
                        "Java.perform(function() {\n"
                        "    try {\n"
                        f"        var clazz = Java.use('{class_name}');\n"
                        f"        {method_access}.implementation = function() {{\n"
                        "            if (GLOBAL_FAKE_LOGGED_IN) {\n"
                        f"                console.log('[+] Fake logged-in state: {class_name}.{method} -> true');\n"
                        f"{forced_return}"
                        "            }\n"
                        f"{original_return}"
                        "        };\n"
                        "    } catch (e) { console.error('[-] Login hook error: ' + e.message); }\n"
                        "});"
                    ),
                }
            elif method_kind == "login-gate":
                user_options = [
                    f"Vo hieu hoa `{class_name}->{method}()` de khong chuyen nguoi dung toi man hinh dang nhap.",
                    f"Hook `{class_name}.{method}` de bo qua gate bat buoc dang nhap.",
                    "Kiem tra cac nhanh if-eqz/if-nez quanh loi goi gate de dao nguoc dieu kien.",
                ]
                auto_strategy = {
                    "action_type": "skip_login_gate",
                    "target_class": class_name,
                    "target_method": method,
                    "patch_mode": "skip_login_gate",
                    "method_kind": method_kind,
                    "return_type": return_type,
                    "frida_hook_script": (
                        "Java.perform(function() {\n"
                        "    try {\n"
                        f"        var clazz = Java.use('{class_name}');\n"
                        f"        {method_access}.implementation = function() {{\n"
                        "            if (GLOBAL_SKIP_LOGIN_GATE) {\n"
                        f"                console.log('[+] Login gate bypassed: {class_name}.{method}');\n"
                        f"{forced_return}"
                        "            }\n"
                        f"{original_return}"
                        "        };\n"
                        "    } catch (e) { console.error('[-] Login gate hook error: ' + e.message); }\n"
                        "});"
                    ),
                }
            else:
                user_options = [
                    f"Patch `{class_name}->{method}()` tra ve ket qua dang nhap thanh cong.",
                    f"Hook `{class_name}.{method}` bang Frida de gia lap xac thuc thanh cong.",
                    "Hook FirebaseAuth.getCurrentUser()/signInWithEmailAndPassword() neu dung Firebase.",
                ]
                auto_strategy = {
                    "action_type": "force_login_success",
                    "target_class": class_name,
                    "target_method": method,
                    "override_value": True,
                    "patch_mode": "force_login_success",
                    "method_kind": method_kind,
                    "return_type": return_type,
                    "frida_hook_script": (
                        "Java.perform(function() {\n"
                        "    try {\n"
                        f"        var clazz = Java.use('{class_name}');\n"
                        f"        {method_access}.implementation = function() {{\n"
                        "            if (GLOBAL_LOGIN_BYPASS) {\n"
                        f"                console.log('[+] Login forced success: {class_name}.{method}');\n"
                        f"{forced_return}"
                        "            }\n"
                        f"{original_return}"
                        "        };\n"
                        "    } catch (e) { console.error('[-] Login bypass hook error: ' + e.message); }\n"
                        "});"
                    ),
                }

        elif category == "xac minh toan ven":
            user_options = [
                "Nop phuong thuc kiem tra Signature/Checksum.",
                "Hook PackageInfo/Signature tra ve Chu ky goc cua ung dung.",
            ]
            auto_strategy = {
                "action_type": "bypass_integrity",
                "target_class": class_name,
                "patch_mode": "mock_signature",
            }

        else:
            user_options = [
                f"Theo doi luong thuc thi cua {method} bang Frida trace.",
                "Vo hieu hoa phuong thuc bang lệnh return-void.",
            ]
            auto_strategy = {
                "action_type": "generic_observe",
                "patch_mode": "log_call",
            }

        return {
            "user_options": user_options,
            "auto_strategy": auto_strategy,
        }

    # =====================================================
    # DO TIN CAY
    # =====================================================

    def _confidence(
        self,
        behavior_confidence: float,
        evidence_weight: float,
    ) -> float:

        score = behavior_confidence * 0.60 + evidence_weight * 0.40
        return round(min(max(score, 0.0), 1.0), 4)

    # =====================================================
    # GOP MUC TIEU
    # =====================================================

    def _merge_targets(
        self,
        targets: list[Target],
    ) -> list[Target]:

        merged: dict[tuple, Target] = {}

        for target in targets:
            key = (
                target.category,
                target.class_name,
                target.method,
            )

            if key not in merged:
                merged[key] = target
                continue

            current = merged[key]
            self._merge_target_into(current, target)

        # Gop target khong ro method vao target cung class/category neu da co method manh hon.
        for key, target in list(merged.items()):
            if target.method:
                continue

            for other_key, other in merged.items():
                if other_key == key or not other.method:
                    continue
                if (
                    target.category == other.category
                    and target.class_name == other.class_name
                ):
                    self._merge_target_into(other, target)
                    merged.pop(key, None)
                    break

        return sorted(
            merged.values(),
            key=lambda x: (
                -target_bypass_score(x),
                -target_evidence_score(x),
                -x.confidence,
                x.category,
                x.source,
                x.line or 0,
            ),
        )

    def _merge_target_into(self, current: Target, incoming: Target) -> None:
        if incoming.confidence >= current.confidence:
            current.source = incoming.source or current.source
            current.line = incoming.line or current.line
            current.reason = incoming.reason or current.reason
        current.confidence = max(current.confidence, incoming.confidence)
        current.evidence.extend(incoming.evidence)
        current.details.update(incoming.details)
        if incoming.suggested_actions.get("auto_strategy"):
            current.suggested_actions["auto_strategy"].update(
                incoming.suggested_actions["auto_strategy"]
            )

    # =====================================================
    # XUAT DU LIEU
    # =====================================================

    def to_dict(
        self,
        targets: list[Target],
    ) -> list[dict[str, Any]]:
        """Xuat du lieu danh sach Target ra Dict mac dinh."""
        return [target.to_dict() for target in targets]

    def to_frida_config(
        self,
        targets: list[Target],
        app_package: str = "com.example.app",
    ) -> dict[str, Any]:
        """Xuat danh sach Target ra Dict cau hinh chuan nap truc tiep cho Frida Engine."""
        hooks = []
        for target in targets:
            if not target.is_frida_hookable():
                continue
            hook = target.to_frida_hook_config()
            if hook.get("frida_script"):
                hooks.append(hook)
        return {
            "metadata": {
                "generated_by": "APK Target Analyzer - Frida Engine",
                "version": "2.0-frida",
                "target_package": app_package,
                "total_hooks": len(hooks),
            },
            "global_settings": {
                "auto_start": True,
                "log_level": "verbose",
            },
            "hooks": hooks,
        }

    def export_frida_json(
        self,
        targets: list[Target],
        output_file: str | Path,
        app_package: str = "com.example.app",
    ) -> Path:
        """Ghi cau hinh ra file .json chuan cho Frida."""
        out_path = Path(output_file)
        config = self.to_frida_config(targets, app_package=app_package)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return out_path
if __name__ == "__main__":
    # Thu mức chua ma nguon Smali da giai nen
    smali_dir = "./smali_out"
    analyzer = TargetAnalyzer(root=smali_dir)

    # 1. Nhan danh sach behaviors tu cong cu quet ma Smali cua ban
    # (behaviors = ...)

    # 2. Phan tich cac vi tri can hook
    targets = analyzer.analyze(behaviors)

    # 3. BAT BUOC: Goi ham xuat file frida_hooks_config.json
    if targets:
        out_file = analyzer.export_frida_json(
            targets=targets,
            output_file="frida_hooks_config.json",
            app_package="com.app.target" # Thay bang package name cua ung dung
        )
        print(f"[+] Da tao file Frida config thanh cong tai: {out_file}")
    else:
        print("[-] Khong tim thay target phu hop de xuat file config JSON.")
        
