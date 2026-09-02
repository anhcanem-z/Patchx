#!/usr/bin/env python3
"""
Script dong bo va chuan hoa cau truc module PatchX
"""
import os
from pathlib import Path

# Xac dinh thu mức goc cua du an
PROJECT_ROOT = Path(__file__).resolve().parent
BEHAVIOR_DIR = PROJECT_ROOT / "patchx_core" / "behavior"

BEHAVIOR_DIR.mkdir(parents=True, exist_ok=True)

# 1. chuan hoa behavior/__init__.py
INIT_CONTENT = '''from .crypto_interceptor import CryptoInterceptorGenerator
from .frida_generator import FridaScriptGenerator, frida_main, main

__all__ = [
    "CryptoInterceptorGenerator",
    "FridaScriptGenerator",
    "frida_main",
    "main",
]
'''

# 2. Chuan hoa behavior/crypto_interceptor.py
CRYPTO_CONTENT = '''from __future__ import annotations


class CryptoInterceptorGenerator:
    """Tao Frida Script theo doi va giai ma du lieu ma hoa HTTP/Crypto tu xa."""

    @staticmethod
    def generate_crypto_hooks() -> str:
        return """
    // =====================================================
    // CRYPTO INTERCEPTOR & DECRYPTION MONITOR
    // =====================================================
    try {
        var Cipher = Java.use('javax.crypto.Cipher');
        var SecretKeySpec = Java.use('javax.crypto.spec.SecretKeySpec');
        var StringClass = Java.use('java.lang.String');

        // Hook Cipher.doFinal(byte[]) de bat du lieu Truoc/Sau giai ma
        Cipher.doFinal.overload('[B').implementation = function (input) {
            var result = this.doFinal(input);
            try {
                var mode = this.getOptmode(); // 1 = ENCRYPT, 2 = DECRYPT
                var algo = this.getAlgorithm();
                var plainText = StringClass.$new(mode === 2 ? result : input);
                
                console.log('[CRYPTO] Algo: ' + algo + ' | Mode: ' + (mode === 2 ? 'DECRYPT' : 'ENCRYPT'));
                console.log('[CRYPTO] Data: ' + plainText.toString());

                if (plainText.contains('"is_vip"') || plainText.contains('"status"') || plainText.contains('"config"')) {
                    console.log('[!] PHAT HIEN PAYLOAD CAU HINH TU XA: ' + plainText);
                    send({ type: 'CRYPTO_PAYLOAD_DETECTED', algo: algo, payload: plainText.toString() });
                }
            } catch (e) {}
            return result;
        };
        console.log('[+] Crypto Interceptor Hooked Successfully');
    } catch (err) {
        console.log('[-] Crypto Hook Error: ' + err);
    }
"""
'''

# 3. Chuan hoa behavior/frida_generator.py
FRIDA_GEN_CONTENT = '''from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

try:
    from .crypto_interceptor import CryptoInterceptorGenerator
except ImportError:
    from crypto_interceptor import CryptoInterceptorGenerator


class FridaScriptGenerator:
    """Bien dich Script Frida ket hop giua Hook tu dong, Generic SSL Bypass, Crypto Interceptor va Frida RPC Control."""

    def __init__(self):
        self.hooks: List[str] = []

    def generate(self, targets: List[Any], output_file: str | Path = "generated_hook.js") -> str:
        self.hooks.clear()

        header = (
            "// Dynamic Frida Agent - Controlled via RPC\\n"
            "var GLOBAL_VIP_OVERRIDE = true;\\n"
            "var GLOBAL_SSL_BYPASS = true;\\n"
            "var MOCK_API_RESPONSE = null;\\n\\n"
            "Java.perform(function () {\\n"
            "    console.log('[+] Dynamic Frida RPC Engine Initialized');\\n"
        )

        crypto_code = CryptoInterceptorGenerator.generate_crypto_hooks()

        ssl_generic_bypass = (
            "    // --- Generic SSL Pinning Bypass ---\\n"
            "    try {\\n"
            "        var array_list = Java.use('java.util.ArrayList');\\n"
            "        var TrustManager = Java.use('javax.net.ssl.X509TrustManager');\\n"
            "        var SSLContext = Java.use('javax.net.ssl.SSLContext');\\n"
            "        var TrustManagerImpl = Java.registerClass({\\n"
            "            name: 'com.bypass.TrustManager',\\n"
            "            implements: [TrustManager],\\n"
            "            methods: {\\n"
            "                checkClientTrusted: function (chain, authType) {},\\n"
            "                checkServerTrusted: function (chain, authType) {},\\n"
            "                getAcceptedIssuers: function () { return []; }\\n"
            "            }\\n"
            "        });\\n"
            "        var TrustManagers = [TrustManagerImpl.$new()];\\n"
            "        var SSLContext_init = SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom');\\n"
            "        SSLContext_init.implementation = function (keyManager, trustManager, secureRandom) {\\n"
            "            SSLContext_init.call(this, keyManager, TrustManagers, secureRandom);\\n"
            "        };\\n"
            "        console.log('[+] Generic SSL Pinning Bypassed');\\n"
            "    } catch (err) { console.log('[-] SSL Bypass Notice: ' + err); }\\n"
        )

        for target in targets:
            target_dict = target.to_dict() if hasattr(target, "to_dict") else target
            strategy = target_dict.get("suggested_actions", {}).get("auto_strategy", {}) if isinstance(target_dict, dict) else {}
            frida_code = strategy.get("frida_hook_script")

            if frida_code and frida_code not in self.hooks:
                self.hooks.append(frida_code)

        body = "\\n\\n".join(f"    // Hook Entry {i+1}\\n    {code}" for i, code in enumerate(self.hooks))

        rpc_exports = """
// =====================================================
// RPC CONTROL INTERFACE (DIEU KHIEN HANH VI TU XA)
// =====================================================
rpc.exports = {
    setVipStatus: function (enable) {
        GLOBAL_VIP_OVERRIDE = enable;
        console.log('[RPC] Command Received: Set VIP = ' + enable);
        return 'SUCCESS_VIP_' + enable;
    },
    overrideApiResponse: function (jsonStr) {
        MOCK_API_RESPONSE = jsonStr;
        console.log('[RPC] Command Received: Mock API Response Loaded');
        return 'SUCCESS_MOCK_LOADED';
    },
    toggleSslBypass: function (enable) {
        GLOBAL_SSL_BYPASS = enable;
        console.log('[RPC] Command Received: Toggle SSL Bypass = ' + enable);
        return 'SUCCESS_SSL_' + enable;
    }
};
"""

        footer = "\\n});\\n"
        full_script = f"{header}\\n{crypto_code}\\n{ssl_generic_bypass}\\n{body}{footer}\\n{rpc_exports}"

        if output_file:
            Path(output_file).write_text(full_script, encoding="utf-8")

        return full_script


def frida_main(input_file: str | Path | None = None, output_file: str | Path = "generated_hook.js", *args, **kwargs):
    """Ham thuc thi ho tro ca truyen tham so truc tiep tu cli.py va qua argparse."""
    if input_file is None:
        parser = argparse.ArgumentParser(description="Bo sinh script Frida PatchX")
        parser.add_argument("-i", "--input", required=True, help="Duong dan tệp dau vao")
        parser.add_argument("-o", "--output", default="generated_hook.js", help="Duong dan tệp JS xuat ra")

        args_parsed = parser.parse_args()
        input_path = Path(args_parsed.input)
        out_file = args_parsed.output
    else:
        input_path = Path(input_file)
        out_file = output_file

    if not input_path.exists():
        print(f"[-] Loi: Khong tim thay tệp dau vao: {input_path}")
        sys.exit(1)

    targets = []
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                targets = data
            elif isinstance(data, dict):
                targets = data.get("targets", data.get("patches", [data]))
    except json.JSONDecodeError:
        print(f"[!] Tep {input_path} khong phai dang JSON, se tao Frida Script co ban (Crypto + SSL Bypass).")

    generator = FridaScriptGenerator()
    generator.generate(targets, output_file=out_file)
    print(f"[+] Da tao Frida Agent thanh cong: {out_file}")


main = frida_main

if __name__ == "__main__":
    frida_main()
'''


def run_sync():
    print("[*] Dang dong bo hoa toan bo source PatchX...")

    # Ghi file behavior/__init__.py
    (BEHAVIOR_DIR / "__init__.py").write_text(INIT_CONTENT, encoding="utf-8")
    print("  [+] Synchronized: patchx_core/behavior/__init__.py")

    # Ghi file behavior/crypto_interceptor.py
    (BEHAVIOR_DIR / "crypto_interceptor.py").write_text(
        CRYPTO_CONTENT, encoding="utf-8"
    )
    print("  [+] Synchronized: patchx_core/behavior/crypto_interceptor.py")

    # Ghi file behavior/frida_generator.py
    (BEHAVIOR_DIR / "frida_generator.py").write_text(
        FRIDA_GEN_CONTENT, encoding="utf-8"
    )
    print("  [+] Synchronized: patchx_core/behavior/frida_generator.py")

    print("[✔] Hoan tat dong bo! Hay thu chay lai lệnh patchx frida.")


if __name__ == "__main__":
    run_sync()
