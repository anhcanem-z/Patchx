from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import frida
except ImportError:
    frida = None


class DynamicRemoteController:
    """Tram dieu khien tuong tac gui lệnh Bypass thoi gian thuc toi APK thong qua Frida RPC."""

    def __init__(self, package_name: str, device_id: Optional[str] = None):
        if frida is None:
            raise ImportError("Vui long cai đạt thu vien frida-tools: pip install frida-tools")

        self.package_name = package_name
        self.device_id = device_id
        self.session = None
        self.script = None
        self.events: list[dict[str, Any]] = []
        self.condition_rules: list[dict[str, Any]] = []
        self.observation_path: Optional[Path] = None

    def _resolve_device(self):
        """Tra ve device Frida; ho tro tcp:host:port cho Gadget listen cung may."""
        device_id = self.device_id
        if device_id:
            if device_id.startswith("tcp:"):
                address = device_id[4:]
                return frida.get_device_manager().add_remote_device(address)
            if ":" in device_id and not device_id.startswith("usb"):
                return frida.get_device_manager().add_remote_device(device_id)
            return frida.get_device(device_id)
        return frida.get_usb_device()

    def connect_and_inject(self, js_script_path: str, mode: str = "spawn"):
        """Ket noi toi thiet bi Android va nap Agent JS.

        mode = "spawn": can frida-server; spawn app truoc roi inject.
        mode = "attach": danh cho Frida Gadget; app phai dang chay va gadget
                         phai dung interaction type "listen".
        """
        device = self._resolve_device()
        print(f"[*] Da ket noi thiet bi: {device.name}")

        with open(js_script_path, "r", encoding="utf-8") as f:
            script_code = f.read()

        if mode == "attach":
            target = self.package_name
            try:
                process = device.get_process(self.package_name)
                target = process.pid
            except Exception:
                target = None
                try:
                    for process in device.enumerate_processes():
                        name = process.name or ""
                        if self.package_name in name or "gadget" in name.lower():
                            target = process.pid
                            break
                except Exception:
                    pass
            if target is None:
                target = self.package_name
            self.session = device.attach(target)
        else:
            pid = device.spawn([self.package_name])
            self.session = device.attach(pid)

        self.script = self.session.create_script(script_code)
        self.script.on("message", self._on_message)
        self.script.load()

        if mode != "attach":
            device.resume(pid)
        print(f"[+] Da Inject Agent RPC vao tien trinh: {self.package_name}")

    def _on_message(self, message: dict, data: Any):
        """Xu ly su kien gui ve tu Frida Agent, luu log va kiem tra dieu kien."""
        payload = message.get("payload", {})
        event = {
            "timestamp": time.time(),
            "type": message.get("type"),
            "payload": payload,
            "message": message,
        }
        self.events.append(event)

        if message.get("type") == "send":
            print(f"\n[AGENT NOTIFY] {json.dumps(payload, indent=2, ensure_ascii=False)}")
        else:
            print(f"\n[AGENT LOG] {message}")

        if self.observation_path is not None:
            try:
                with open(self.observation_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError:
                pass

        self._apply_condition_rules(event)

    def start_observation(self, log_file: str | Path | None = None):
        """Bat dau ghi nhat ky quan sat; neu khong truyen duong dan thi chi giu RAM."""
        self.events.clear()
        self.observation_path = Path(log_file) if log_file else None
        if self.observation_path is not None:
            self.observation_path.parent.mkdir(parents=True, exist_ok=True)
        return self

    def add_condition_rule(self, rule: dict[str, Any]):
        """Them quy tac dieu khien theo dieu kien.

        Quy tac vi du:
        {
            "match": ["vip_check", "false"],
            "command": "set_vip_status",
            "value": true
        }
        """
        if not isinstance(rule, dict):
            raise ValueError("rule phai la dict")
        if not rule.get("command"):
            raise ValueError("rule can co command")
        self.condition_rules.append(rule)
        return self

    def _apply_condition_rules(self, event: dict[str, Any]):
        """Kiem tra moi su kien quan sat, neu trung dieu kien thi thuc thi lệnh RPC."""
        if not self.condition_rules or self.script is None:
            return

        haystack = json.dumps(event, ensure_ascii=False).lower()
        for rule in self.condition_rules:
            needles = rule.get("match") or []
            if not needles:
                continue
            if not all(str(needle).lower() in haystack for needle in needles):
                continue

            command = rule.get("command")
            value = rule.get("value", True)
            if command == "set_vip_status":
                self.command_override_vip(enable=bool(value))
            elif command == "toggle_ssl_bypass":
                self.command_toggle_ssl_bypass(enable=bool(value))
            elif command == "override_api_response":
                self.command_inject_mock_response(str(value))
            elif command == "set_fake_logged_in":
                self.command_fake_logged_in(enable=bool(value))
            elif command == "set_login_bypass":
                self.command_login_bypass(enable=bool(value))
            elif command == "set_skip_login_gate":
                self.command_skip_login_gate(enable=bool(value))
            else:
                print(f"[!] Chua ho tro lệnh dieu kien: {command}")

    def save_observation(self, log_file: str | Path):
        """Ghi toan bo su kien da quan sat ra mot file JSON."""
        out = Path(log_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(self.events, fh, ensure_ascii=False, indent=2)
        print(f"[+] Da luu nhat ky quan sat: {out}")
        return out

    # =====================================================
    # LỆNH DIEU KHIEN REMOTE BYPASS (RPC CALLS)
    # =====================================================

    def command_override_vip(self, enable: bool = True):
        """Ra lệnh bat/tat trang thai VIP truc tiep trong RAM."""
        if self.script:
            res = self.script.exports_sync.set_vip_status(enable)
            print(f"[+] Ket qua ra lệnh Bypass VIP: {res}")

    def command_inject_mock_response(self, json_string: str):
        """Ra lệnh thay the du lieu JSON ma hoa tra ve tu API Server."""
        if self.script:
            res = self.script.exports_sync.override_api_response(json_string)
            print(f"[+] Ket qua ghi de Response: {res}")

    def command_toggle_ssl_bypass(self, enable: bool = True):
        """Bat/Tat bo qua kiem tra SSL Pinning linh hoat."""
        if self.script:
            res = self.script.exports_sync.toggle_ssl_bypass(enable)
            print(f"[+] Trang thai SSL Bypass: {res}")

    def command_fake_logged_in(self, enable: bool = True):
        """Bat/Tat gia lap trang thai da dang nhap trong RAM."""
        if self.script:
            res = self.script.exports_sync.set_fake_logged_in(enable)
            print(f"[+] Trang thai Fake Logged In: {res}")

    def command_login_bypass(self, enable: bool = True):
        """Bat/Tat ep xac thuc dang nhap luon thanh cong."""
        if self.script:
            res = self.script.exports_sync.set_login_bypass(enable)
            print(f"[+] Trang thai Login Bypass: {res}")

    def command_skip_login_gate(self, enable: bool = True):
        """Bat/Tat bo qua man hinh/gate bat buoc dang nhap."""
        if self.script:
            res = self.script.exports_sync.set_skip_login_gate(enable)
            print(f"[+] Trang thai Skip Login Gate: {res}")
