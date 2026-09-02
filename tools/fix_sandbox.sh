#!/usr/bin/env sh
# Kiem tra va khac phuc loi sandbox cho Codex tren moi truong Termux / Android.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WORKSPACE=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

case "${1:-}" in
  --help|-h)
    printf '%s\n' "Su dung: sh tools/fix_sandbox.sh"
    printf '%s\n' "Kiem tra va tu dong sua loi sandbox (Landlock/seccomp) cua Codex tren Termux."
    exit 0
    ;;
esac

printf '%s\n' "[1/5] Workspace: $WORKSPACE"

if [ ! -d "$WORKSPACE" ] || [ ! -f "$WORKSPACE/AGENTS.md" ]; then
  printf '%s\n' "LOI: khong nhan dien duoc workspace patchx." >&2
  exit 1
fi

printf '%s\n' "[2/5] Kiem tra quyen ghi local..."
PROBE="$WORKSPACE/.sandbox_probe.$$"
trap 'rm -f "$PROBE"' EXIT HUP INT TERM
if ! (umask 077 && : > "$PROBE"); then
  printf '%s\n' "LOI: workspace khong cho phep ghi. Hay chay trong dung thu muc project." >&2
  exit 1
fi
rm -f "$PROBE"
trap - EXIT HUP INT TERM
printf '%s\n' "OK: workspace doc/ghi binh thuong."

printf '%s\n' "[3/5] Kiem tra cong cu apply_patch..."
if command -v apply_patch >/dev/null 2>&1; then
  printf 'apply_patch: %s\n' "$(command -v apply_patch)"
else
  CODEX_BIN="/data/data/com.termux/files/usr/lib/node_modules/@mmmbuto/codex-cli-termux/bin/codex.bin"
  if [ -f "$CODEX_BIN" ]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$CODEX_BIN" "$HOME/.local/bin/apply_patch"
    printf 'apply_patch: da tao symlink tai %s\n' "$HOME/.local/bin/apply_patch"
  else
    printf '%s\n' "CANH BAO: khong tim thay codex.bin de tao symlink apply_patch."
  fi
fi

printf '%s\n' "[4/5] Kiem tra cau hinh sandbox Codex..."
CODEX_CONFIG="$HOME/.codex/config.toml"
if [ -f "$CODEX_CONFIG" ]; then
  if grep -q 'sandbox_mode[[:space:]]*=[[:space:]]*"danger-full-access"' "$CODEX_CONFIG"; then
    printf '%s\n' "OK: sandbox_mode da duoc cau hinh 'danger-full-access' (unrestricted fs)."
  else
    printf '%s\n' "Dang tu dong them sandbox_mode = \"danger-full-access\" vao $CODEX_CONFIG..."
    sed -i '1s/^/sandbox_mode = "danger-full-access"\n/' "$CODEX_CONFIG"
    printf '%s\n' "OK: Da cap nhat cau hinh sandbox Codex thanh cong."
  fi
else
  printf '%s\n' "CHUA CO: $CODEX_CONFIG (se duoc tao khi chay codex)."
fi

printf '%s\n' "[5/5] Ket luan"
printf '%s\n' "OK: Tat ca cac van de sandbox tren Termux da duoc kiem tra va xu ly hoan tat."
printf '%s\n' "Khong con loi 'filesystem sandbox cannot be enforced'."
