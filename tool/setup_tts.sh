#!/data/data/com.termux/files/usr/bin/bash
set -u

echo "=== Smart Dubbing: TTS setup ==="

TERMUX_TTS="$(command -v termux-tts-speak 2>/dev/null || true)"
ESPEAK="$(command -v espeak-ng 2>/dev/null || command -v espeak 2>/dev/null || true)"

if [ -n "$TERMUX_TTS" ]; then
    echo "[OK] termux-tts-speak: $TERMUX_TTS"
    echo
    echo "Thử giọng Việt..."
    "$TERMUX_TTS" -l vi -r 1.0 "Xin chào, đây là giọng đọc thông minh."

    if [ $? -eq 0 ]; then
        cat > tts.conf <<CONF
TTS_BACKEND=termux
TTS_BIN=$TERMUX_TTS
TTS_LANG=vi
TTS_RATE=1.0
CONF
        echo
        echo "[OK] Đã chọn Termux Android TTS."
        echo "[OK] Cấu hình: ~/smart-dubbing/tts.conf"
        exit 0
    fi
fi

if [ -n "$ESPEAK" ]; then
    echo "[OK] espeak: $ESPEAK"
    cat > tts.conf <<CONF
TTS_BACKEND=espeak
TTS_BIN=$ESPEAK
TTS_LANG=vi
TTS_RATE=1.0
CONF
    echo "[OK] Đã chọn eSpeak."
    exit 0
fi

echo
echo "[FAIL] Không tìm thấy TTS chạy được trên Android."
echo
echo "Cài Termux:API + package termux-api rồi chạy lại:"
echo
echo "  pkg install termux-api"
echo "  ./setup_tts.sh"
exit 1
