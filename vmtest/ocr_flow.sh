#!/system/bin/sh
export PATH=$PATH:/system/bin:/system/xbin
P=vn.smartdubbing.live
tap_text() {
  su -c "uiautomator dump /sdcard/uiX.xml" >/dev/null 2>&1
  local node=$(su -c "cat /sdcard/uiX.xml" | tr '>' '>\n' | grep "$1" | head -1)
  local b=$(echo "$node" | grep -o '\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]' | head -1 | sed 's/\[//;s/\]\[/ /;s/\]//;s/,/ /g')
  if [ -z "$b" ]; then echo "NOT FOUND: $1"; return 1; fi
  set -- $b
  local x=$(( ($1 + $3) / 2 )) y=$(( ($2 + $4) / 2 ))
  echo "tap '$1' center=($x,$y)"
  su -c "input tap $x $y"
  sleep 2
}
su -c "am start -n $P/.MainActivity"
sleep 3
tap_text "Gemini Live"
tap_text "OCR — đọc"
tap_text "BẮT ĐẦU ĐỌC CHỮ"
sleep 4
echo "svc=$(su -c \"dumpsys activity services $P 2>/dev/null\" | grep -c AudioCaptureService)"
su -c "am start -a android.intent.action.VIEW -d 'https://en.m.wikipedia.org/wiki/Android_(operating_system)' com.android.chrome" >/dev/null 2>&1
sleep 18
su -c "tail -25 /data/data/$P/files/live_dub_debug.log"
