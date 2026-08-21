# Fixture mẫu — tests/fixtures/mau/

Bộ dữ liệu mẫu dùng chung cho test suite, tách khỏi dữ liệu thật (`Apks/`,
`upgraded/`) để test nhanh, nhẹ, tái lập được. Mọi fixture trong thư mục này
được **sinh bằng script** `generate_mau.py` — không sửa tay file nhị phân.

## Các fixture

| Fixture | Dùng cho | Nội dung |
|---|---|---|
| `libdemo64.so` | `rodata_patcher`, `rodata_bypass`, `smart-scan` | ELF64 ET_DYN giả, `.rodata` tại RVA `0x1000` chứa 2 chuỗi: `https://api.old-server.com/v1`, `https://config.example.com/patchx.json` |
| `libdemo32.so` | `rodata_patcher` (ELF32) | ELF32 giả, `.rodata` tại RVA `0x1000` chứa 1 chuỗi |
| `libdup.so` | `rodata_patcher` (nhiều vị trí) | ELF64 giả, `.rodata` chứa `S0` lặp 2 lần + `S1` |
| `libsmart.so` | `smart_scanner` | ELF64 ARM64: `.text` ADRP+ADD + LDR literal, `.dynsym` hàm JNI, `.rodata` 5 chuỗi (endpoint/JWT/log/sample/library) |
| `libmini_a.so` | `start_scan` | ELF64 tối giản: endpoint + log noise |
| `libmini_b.so` | `start_scan` | ELF64 tối giản: AWS key + sample noise |
| `libmini_c.so` | `start_scan` | ELF64 tối giản: 1 endpoint (bản x86) |
| `smali_tree/` | `start_scan`, `smart_scanner`, `apply`, `validate_tree` | Cây APK giả lập nhỏ: `AndroidManifest.xml`, `apktool.yml`, `smali/com/demo/MainActivity.smali` + `Util.smali` |
| `patch_mau.zip` | `parser`, `audit`, `apply` | Patch zip mẫu: `ADD_FILES` (save.smali) + `MATCH_REPLACE` trên `[LAUNCHER_ACTIVITIES]` |
| `patch_mau/` | đọc/sửa nội dung patch | Bản giải nén của `patch_mau.zip` (`patch.txt`, `save.smali`) |

## Cách dùng trong test

Tham chiếu qua đường dẫn tuyệt đối, không hard-code tương đối:

```python
import os
FIXTURES_MAU = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "fixtures", "mau")
so = os.path.join(FIXTURES_MAU, "libdemo64.so")
tree = os.path.join(FIXTURES_MAU, "smali_tree")
zpath = os.path.join(FIXTURES_MAU, "patch_mau.zip")
```

Ví dụ kiểm chứng ELF mẫu với `rodata_patcher`:

```python
from patchx_core.behavior.rodata_patcher import (
    ElfReader, find_string_offsets)
r = ElfReader(so)
assert any(s["name"] == ".rodata" for s in r.list_alloc_sections())
hits = find_string_offsets(so, "https://api.old-server.com/v1")
assert len(hits) == 1 and hits[0].rva == 0x1000
```

Lưu ý: nếu patch mẫu vào file ELF thì thao tác trên **bản sao** trong thư
mục tạm, không ghi đè fixture gốc (các test đều `shutil.copy2` fixture sang
TMP trước khi sửa).

## Test dùng fixture mẫu

- `test_rodata_patcher` — `libdemo64.so` / `libdemo32.so` / `libdup.so`
- `test_rodata_bypass_flows` — `libdemo64.so`
- `test_start_scan` — `libmini_a.so` / `libmini_b.so` / `libmini_c.so`
- `test_smart_scanner` — `libsmart.so`
- `test_fixtures_mau` — kiểm chứng chung (ELF, smali tree, patch zip)

## Tái sinh

```sh
python3 tests/fixtures/mau/generate_mau.py
```

Chạy lại sau khi đổi chuỗi/cấu trúc mẫu; script ghi đè toàn bộ fixture
trong thư mục này.
