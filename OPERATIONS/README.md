# Điều hướng vận hành PATCHX

`OPERATIONS/` là lớp phân loại hiển thị, không phải nơi chứa bản sao. Mọi
đường dẫn thật được khai báo trong `NAVIGATION.json`; công cụ có thể đọc tệp
này để nhận dạng đúng nhóm dữ liệu mà không làm hỏng tham chiếu cũ.

| Nhóm | Nội dung | Nguồn thật |
|---|---|---|
| `00_operations` | Quy tắc, trạng thái, hướng dẫn lệnh | `AGENTS.md`, `AGENTS_TRANG_THAI.md`, `README.md`, `HUONG_DAN_*.txt` |
| `01_source_code` | CLI, lõi, behavior, tool | `patchx`, `patchx_core/`, `patchx_toolkit.py`, `tools/`, script dev |
| `02_patch_data` | APK gốc, patch, combo | `Apks/`, `upgraded/`, `combos/`, `combos_auto/`, `hook_remote_data_control/`, `demo-apk/` |
| `03_apk_labs` | Cây giải mã, APK build/patch/gadget | `outputs/apk/apk-trees/`, `outputs/apk/apk-build/`, `outputs/apk/apk-patch/`, `outputs/behavior/gadget/` |
| `04_quality` | Test, baseline, benchmark | `tests/`, `outputs/baseline/`, `outputs/bench/` |
| `05_outputs` | File tự sinh và output theo module | `outputs/` (xem `outputs/README.md`), `dist/` |
| `06_release_archive` | Bản lưu và bản gốc đã xóa | `outputs/backup/`, `.patchx/backup/` |
| `07_mapping` | Bản đồ thư mục output | `outputs/README.md` |

Quy tắc: thao tác trên đường dẫn thật; không di chuyển dữ liệu vào
`OPERATIONS/`. Sau khi thêm một nhóm nguồn mới, cập nhật `NAVIGATION.json`
và kiểm tra toàn bộ target tồn tại.
