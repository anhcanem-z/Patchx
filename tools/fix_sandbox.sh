#!/usr/bin/env sh
# Kiem tra va khac phuc phan local cua loi sandbox cho patchx.
# Khong the thay doi sandbox quan ly boi Codex/executor.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WORKSPACE=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

case "${1:-}" in
  --help|-h)
    printf '%s\n' "Su dung: sh tools/fix_sandbox.sh"
    printf '%s\n' "Kiem tra cwd, quyen ghi trong workspace va apply_patch."
    exit 0
    ;;
esac

printf '%s\n' "[1/4] Workspace: $WORKSPACE"

if [ ! -d "$WORKSPACE" ] || [ ! -f "$WORKSPACE/AGENTS.md" ]; then
  printf '%s\n' "LOI: khong nhan dien duoc workspace patchx." >&2
  exit 1
fi

printf '%s\n' "[2/4] Kiem tra quyen ghi local..."
PROBE="$WORKSPACE/.sandbox_probe.$$"
trap 'rm -f "$PROBE"' EXIT HUP INT TERM
if ! (umask 077 && : > "$PROBE"); then
  printf '%s\n' "LOI: workspace khong cho phep ghi. Hay chay trong dung thu muc project." >&2
  exit 1
fi
rm -f "$PROBE"
trap - EXIT HUP INT TERM
printf '%s\n' "OK: workspace doc/ghi binh thuong."

printf '%s\n' "[3/4] Kiem tra cong cu patch..."
if command -v apply_patch >/dev/null 2>&1; then
  printf 'apply_patch: %s\n' "$(command -v apply_patch)"
else
  printf '%s\n' "CANH BAO: khong tim thay apply_patch trong PATH."
fi

printf '%s\n' "[4/4] Ket luan"
printf '%s\n' "OK: khong co loi quyen local can sua."
printf '%s\n' "Loi 'filesystem sandbox cannot be enforced' nam o executor quan ly."
printf '%s\n' "Hay khoi dong lai phien Codex/executor, sau do mo lai workspace:"
printf '  %s\n' "$WORKSPACE"
printf '%s\n' "Khong dung chmod -R, rm -rf, hoac ghi file ra ngoai workspace de sua loi nay."
