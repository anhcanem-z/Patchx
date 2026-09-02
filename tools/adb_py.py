#!/usr/bin/env python3
"""ADB qua Python (stdlib subprocess) — khong can cai them thu vien."""
import argparse
import subprocess
import sys


def run(*args):
    r = subprocess.run(["adb", *args], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def main():
    p = argparse.ArgumentParser(
        description="ADB qua Python (goi lenh adb CLI, khong can thu vien ngoai)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="danh sach thiet bi")
    c = sub.add_parser("connect", help="ket noi IP:PORT")
    c.add_argument("target")
    d = sub.add_parser("disconnect", help="ngat ket noi")
    d.add_argument("target", nargs="?")
    s = sub.add_parser("shell", help="chay lenh shell tren thiet bi")
    s.add_argument("cmd", nargs=argparse.REMAINDER)
    a = p.parse_args()

    if a.cmd == "devices":
        return run("devices", "-l")
    if a.cmd == "connect":
        return run("connect", a.target)
    if a.cmd == "disconnect":
        return run("disconnect") if not a.target else run("disconnect", a.target)
    if a.cmd == "shell":
        return run("shell", *a.cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
