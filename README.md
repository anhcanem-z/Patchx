# patchx — Bộ script nâng cấp cho "1. PATCH others"

Bộ công cụ thông minh dành cho bộ sưu tập patch APK Editor: quét, kiểm tra
kiến trúc, tự sửa lỗi an toàn, gộp tối ưu, đo độ bao phủ trên APK thật và
xây lộ trình mod.

Quy ước quan trọng: toàn bộ bình luận, tài liệu, thông báo viết bằng tiếng
Việt; còn danh từ/chuỗi trong mã nguồn (khóa patch, mẫu regex, nội dung
smali/XML, tên biến) **giữ nguyên gốc** để không làm thay đổi cấu trúc và
gây lỗi.

## Yêu cầu

- Python 3 (đã kiểm tra trên 3.14)
- Không cần thư viện ngoài

## Các lệnh

Chạy từ thư mục `_patchx`:

| Lệnh | Công dụng |
|------|-----------|
| `python3 patchx scan THƯ_MỤC` | Quét tất cả .zip và in tóm tắt |
| `python3 patchx scan THƯ_MỤC --recursive` | Quét cả thư mục con (bỏ qua _patchx và thư mục nội bộ) |
| `python3 patchx index THƯ_MỤC -o ĐẦU_RA` | Tạo `patchx_index.json` + `patchx_report.md` |
| `python3 patchx dupes THƯ_MỤC` | Phát hiện patch trùng nội dung theo hash → `dupes_report.md` |
| `python3 patchx manifest THƯ_MỤC` | Tạo `MANIFEST.json` toàn cây (thư mục, thư mục trống, nhóm trùng) |
| `python3 patchx report THƯ_MỤC -o report.html [--apk CÂY]` | Báo cáo HTML dashboard: tìm kiếm/lọc + preview diff từng patch; `--apk` kèm độ phủ |
| `python3 patchx analyze CÂY_APK` | Phân tích ngữ nghĩa: packer, nghi mã hóa chuỗi, entry class, call-graph (T1) |
| `python3 patchx model CÂY_APK [--v2] [--bench] [-o app_model.json]` | Tạo mô hình trung gian chỉ-đọc; `--v2` thêm identity exact/structural/semantic, caller/callee và khoảng cách từ entry; `--bench` chỉ đo cache lạnh, không ghi JSON |
| `python3 patchx semantic-plan CÂY_APK KẾ_HOẠCH.json [--model MODEL.json] [--verbose]` | Đối chiếu mục tiêu + điều kiện với app-model; plan V2 chặn `AMBIGUOUS_TARGET` và yêu cầu model V2 trước khi trả `READY_FOR_PREFLIGHT`; `--verbose` in ứng viên bị loại, lý do thiếu điều kiện và gợi ý siết/nới selector |
| `python3 patchx plan-compile CÂY_APK PLAN_V2.json -o draft.json` | Khóa evidence theo hash cây và tạo transaction nháp `DRAFT_REQUIRES_APPROVAL`; không tạo patch thực thi, không gọi `apply` |
| `python3 patchx plan-preflight CÂY_APK draft.json [-o draft_mới.json]` | Kiểm tra hash evidence; nếu cây đổi sẽ tự đánh giá lại plan V2 — vẫn `READY` thì ghi draft mới qua `-o`, còn mơ hồ/không đủ bằng chứng thì `BLOCKED`; không sửa cây APK |
| `python3 patchx acceptance FIXTURE [-o report.json]` | Chạy tiêu chí nghiệm thu V2 từ `acceptance.json`: tái lập model, tái nhận diện sau obfuscation, dương tính giả selector, mơ hồ/không tự tin bị chặn |
| `python3 patchx remote-map CÂY_APK --flow [-o flow.json]` | Dựng bản đồ luồng quyết định/dữ liệu `patchx.decision-flow/v1`: source/transform/decision/sink + đường tới sink |
| `python3 patchx rodata-find FILE.SO [--string CHUỖI] [-o json]` | Tìm RVA (Relative Offset) của chuỗi trong `.rodata`/`.data` của file `.so` — thay bước tìm tay bằng IDA/Ghidra; không truyền `--string` thì liệt kê section ALLOC |
| `python3 patchx rodata-patch FILE.SO --string CHUỖI --new CHUỖI_MỚI [--offset RVA] [--ptr-offset RVA] [--mode inline\|pointer\|both] [--runtime-scan] [-o script.js]` | Sinh script Frida patch chuỗi trong `.rodata` trực tiếp trên RAM: `Memory.protect` rwx → ghi inline (kiểm tra dung lượng) hoặc đổi con trỏ tới chuỗi mới cấp phát (độ dài vô hạn) → khôi phục quyền trang; không sửa file `.so/.elf` gốc |
| `python3 patchx rodata-apply FILE.SO --string CHUỖI --new CHUỖI_MỚI [--offset RVA] [--allow-overflow] [--no-backup] [--out FILE]` | Chèn chuỗi TRỰC TIẾP vào file `.so` (patch file, không cần Frida): tự tìm RVA → ghi tại offset thật + NUL hóa phần dư, có backup trước khi ghi; chặn chuỗi dài hơn chuỗi cũ trừ `--allow-overflow` (giới hạn cố hữu của patch file, khác Frida RAM) |
| `python3 patchx smart-scan FILE.SO [--min-risk N] [--show-noise] [--behaviors] [-o json] [--md md]` | Quét chuỗi .rodata/.data THÔNG MINH: lọc nhiễu ngữ nghĩa (API key/token/endpoint vs log/comment/sample) + static data-flow (ADRP+ADD/LDR literal/LEA rip + symbol table) + xác thực chéo caller/callee JNI (loại false positive) + Risk Weighting & Confidence Score 0-100 kèm bằng chứng + SHA-256; `--behaviors` in từ điển hành vi (smart_ontology.py) |
| `python3 patchx start-scan APK|THU_MỤC|FILE.SO [--abi arm64-v8a] [--min-risk N] [--keep-so] [-o json] [--md md]` | start-scan = xử lý THƯ VIỆN .so HÀNG LOẠT (tách biệt behavior = smali): trích lib/*.so từ APK theo ABI, quét từng lib bằng smart-scan, tổng hợp top findings + bảng từng lib (sha256, refs, JNI, nhiễu) |
| `python3 patchx remote-map CÂY_APK --dataflow [-o flow.json]` | Dựng `patchx.data-flow/v1` với `primary_role`, `roles`, `data_type`, `confidence` và đường decision → sink |
| `python3 patchx knowledge suggest-plan CÂY_APK -o PLAN.json [--db db.json]` | Sinh semantic-plan/V2 tham chiếu từ kho tri thức; `recommendation_only=true`, không tự chọn target hay áp patch |
| `python3 patchx diff-apk GỐC MOD [-o out.zip] [--semantic-plan plan.json] [--version-map map.json] [--semantic-plan-v2 plan-v2.json]` | Sinh patch tương thích từ khác biệt; `--version-map` và `--semantic-plan-v2` chỉ tạo bằng chứng/plan V2 tham chiếu từ ghép method duy nhất, không tự chọn target hay áp patch |
| `python3 patchx suggest-apk THƯ_MỤC CÂY_APK` | Gợi ý chuỗi patch theo APK thật: coverage + danh mục + kho thành công (T4) |
| `python3 patchx suggest-llm THƯ_MỤC "ý định" --approve` | Ý định mod → khung combo; chỉ ghi sau khi người dùng duyệt (T4) |
| `python3 patchx verify-manifest THƯ_MỤC [--manifest ĐƯỜNG_DẪN]` | Xác minh kho theo sha256: phát hiện file thêm/xóa/sửa (T5) |
| `python3 patchx ci THƯ_MỤC -o ĐẦU_RA [--quick]` | Dây chuyền CI: audit → upgrade → optimize → combo-auto → simulate; báo cáo trước/sau (T7) |
| `python3 patchx apk-prepare APK -o CÂY` | Giải mã APK bằng apktool (chuẩn bị cây cho coverage/apply) |
| `python3 patchx audit THƯ_MỤC -o ĐẦU_RA` | Kiểm tra kiến trúc từng patch → `audit.json` + `audit_report.md` |
| `python3 patchx upgrade THƯ_MỤC -o upgraded/` | Nâng cấp: sửa metadata thiếu, thẻ đóng, gộp trùng, chuẩn hóa định dạng |
| `python3 patchx optimize THƯ_MỤC -o optimized/` | Gộp patch cùng mục tiêu, gộp trùng, tách xung đột |
| `python3 patchx combo THƯ_MỤC [--only năng-lực,...] [--auto] [--recursive] -o ĐẦU_RA` | Gộp combo: `--only` theo năng lực chỉ định; `--auto` tự tìm patch bổ trợ theo HỌ chức năng + class-link |
| `python3 patchx coverage PATCH CÂY_APK` | Đo độ bao phủ của patch trên APK đã giải mã |
| `python3 patchx suggest PATCH [CÂY_APK]` | Tự đề xuất cải tiến (kiến trúc + mở rộng chuỗi) |
| `python3 patchx roadmap THƯ_MỤC CÂY_APK -o ĐẦU_RA` | Xếp hạng patch theo mức áp dụng được → `roadmap.md` |
| `python3 patchx apply PATCH... CÂY_APK` | Áp patch lên APK đã giải mã (an toàn: sao lưu + idempotent) |
| `python3 patchx simulate THƯ_MỤC -o ĐẦU_RA [--dex-runner LỆNH] [--apk CÂY_APK]` | Mô phỏng toàn diện: tự sinh mẫu từ regex, áp thử từng patch, chấm hiệu quả + idempotency + thời gian; `--dex-runner` chạy EXECUTE_DEX (an toàn), `--apk` dùng cây APK thật |
| `python3 patchx menu [--list] [--goal TỪ_KHÓA] [--run ID] [--set KEY=VALUE]` | Danh sách chức năng để lựa chọn pipeline: nhóm theo bước luồng + sắp xếp hợp lý; `--goal` tính điểm khớp từ khóa và xếp hạng; `--run ID` chạy pipeline đúng thứ tự (thay placeholder bằng `--set`) |
| `python3 patchx selfcheck [THƯ_MỤC]` | Kiểm tra sức khỏe chính bộ patchx (module + đọc toàn bộ patch) |
| `python3 patchx test` | Chạy bộ tự kiểm tra (146 bài) |

### Toolkit (patchx_toolkit.py)

| Lệnh | Công dụng |
|------|-----------|
| `python3 patchx_toolkit.py doctor` | Kiểm tra môi trường + bộ patch đầu vào |
| `python3 patchx_toolkit.py run` | Full pipeline 12 bước → `outputs/pipeline/` |
| `python3 patchx_toolkit.py package` | Đóng gói phân phối (giữ 3 bản mới nhất) |
| `python3 patchx_toolkit.py list` | Liệt kê patch theo khả năng + combo bổ trợ |
| `python3 patchx_toolkit.py session --select ... --tree CÂY` | Áp chung một phiên patch lên cây APK |
| `python3 patchx_toolkit.py apk-plan CÂY --input upgraded` | Quét + xếp hạng phương án bypass (kèm tỷ lệ %) |
| `python3 patchx_toolkit.py bench-scan CÂY --input upgraded` | Đo tốc độ quét candidate (nghiệm thu < 60s) |
| `python3 patchx_toolkit.py apk-full CÂY --top 3` | End-to-end: plan → apply → fix-res → build → zipalign → sign → verify → báo cáo |
| `python3 patchx_toolkit.py apk-runtime APK [--connect HOST:PORT] [--scan-local] [--expect RE] [--forbid RE]` | Runtime verify M2/M3: cài, mở, logcat, bắt crash; `--connect`/`--scan-local` nối máy ảo cloud (Redfinger/VMOS) trước; thiếu device → báo "thiếu môi trường" |
| `python3 patchx_toolkit.py apk-test / apk-fix-res / apk-patch` | Thử trên APK thật / chuẩn hoá resource `$` / patch + build + ký |
| `python3 patchx_toolkit.py install-deps` | Cài công cụ thiếu (apktool, zipalign, apksigner...) |
| `python3 patchx_toolkit.py plan-ui [--output THƯ_MỤC]` | Sinh trang HTML tương tác chọn patch (điểm, % thành công, cách + công cụ) |
| `python3 patchx_toolkit.py webui [--host IP] [--port 8787] [--open]` | Khởi động **giao diện web toàn diện** cho toàn bộ patchx — mở trên điện thoại qua trình duyệt; `--host 0.0.0.0` để vào từ máy khác/máy ảo |

## Giao diện web trên điện thoại (webui)

```sh
python3 patchx_toolkit.py webui            # mặc định http://127.0.0.1:8787
python3 patchx_toolkit.py webui --host 0.0.0.0 --open   # mở mạng ngoài, tự mở trình duyệt
```

- 5 tab: Trang chủ, Kho patch, Kế hoạch, Áp dụng, Nhật ký — bao phủ toàn bộ
- **6 tab theo mục tiêu nghiệp vụ**: Trang chủ, Vượt chặn, Chỉnh sửa, Hook,
  Quy trình, Kho — nhãn thuần Việt, không hiển thị tên lệnh làm nhãn chính.
  Tab Vượt chặn / Chỉnh sửa / Hook có chip "Bạn muốn làm gì?" dẫn tới thẻ
  mục tiêu (Mở khoá VIP, Ẩn root, Gỡ SSL pinning, Chặn quảng cáo, Bắt API…)
  với 2 nút **Lập kế hoạch** (`apk-plan`) và **Tạo combo sẵn**
  (`combo --only <năng-lực>`).
- Nếu cổng bận, server **tự tắt server web/http cũ** (webui cũ hoặc
  `python3 -m http.server`) rồi dùng lại ĐÚNG cổng — URL luôn ổn định; chỉ
  nhảy cổng khi cổng bị tiến trình lạ chiếm. Khi `--host 0.0.0.0` in kèm IP
  máy để mở từ điện thoại/máy ảo.
- Nút "Chạy" gọi lệnh thật và **stream log theo thời gian thực**; nút "Mở"
  đưa thẳng tới trang kế hoạch vượt chặn (`bypass_plan_ui.html`).
- Thiết kế + nguồn tham khảo: `UI_TOOLKIT_ANDROID.md`.

## Năng lực vượt chặn (bypass) — 22 năng lực

16 năng lực gốc + 6 năng lực mới (16/08/2026): `purchase` (Giả-Lập-Mua-Hàng),
`root-hide` (Ẩn-Root), `ssl-pinning` (Gỡ-SSL-Pinning), `anti-debug`
(Chống-Debug), `frida-hide` (Ẩn-Frida), `emulator` (Bỏ-Kiểm-Tra-Máy-Ảo).

Bộ mẫu bypass nâng cao `bypass_plus/` (13 zip, audit 0 lỗi):
`ssl_pinning_off`, `root_check_off`, `root_su_binary_off`,
`emulator_check_off`, `emulator_fingerprint_off`, `anti_debug_off`,
`anti_tamper_signature_off`, `frida_detect_off`, `iap_fake`,
`iap_purchase_state`, `integrity_verdict_off`, `pro_unlock_vip`.
Sinh combo theo năng lực:

```sh
python3 patchx combo bypass_plus --only ssl-pinning,root-hide -o combos_auto_plus
```

## Luồng làm việc đề xuất

1. `scan` — xem nhanh bộ sưu tập có gì.
2. `audit` — phát hiện lỗi kiến trúc từng patch.
3. `upgrade` — tạo bản patch chuẩn hóa (metadata đủ, thẻ đóng đủ, bỏ trùng).
4. `optimize` — gộp các patch cùng mục tiêu thành patch tối ưu.
5. `combo` — gộp các patch bổ trợ nhau thành combo hiệu quả nhất.
6. `coverage` / `roadmap` — đo trên APK thật xem patch nào áp dụng được.
7. `apply` — áp lên cây APK đã giải mã (apktool d, ...).

## Ví dụ

```sh
cd "1. PATCH others/_patchx"

# 1. Quét
python3 patchx scan .. -o scan.json

# 2. Kiểm tra kiến trúc
python3 patchx audit .. -o .

# 3. Nâng cấp toàn bộ
python3 patchx upgrade .. -o upgraded

# 4. Gộp tối ưu
python3 patchx optimize .. -o optimized

# 5. Gộp combo: bypass VIP + mod shell + kiểm tra toàn vẹn
python3 patchx combo .. --only bypass-license,shell,integrity --recursive

# 6. Gộp combo: truy vết dữ liệu + tìm API + quét token + toàn vẹn
python3 patchx combo .. --only trace,api,token,integrity --recursive

# 7. Đo độ bao phủ một patch trên APK đã giải mã
python3 patchx coverage "../Android_ID.zip" /path/to/decompiled

# 8. Tự đề xuất cải tiến
python3 patchx suggest "../Android_ID.zip" /path/to/decompiled

# 9. Lộ trình mod
python3 patchx roadmap .. /path/to/decompiled -o .

# 10. Áp patch (có sao lưu, không áp lại 2 lần)
python3 patchx apply ../upgraded/Android_ID.zip /path/to/decompiled
```

## Kiến trúc

```
_patchx/
├── patchx                  # điểm vào CLI
├── patchx_core/
│   ├── parser.py           # phân tích patch.txt (biến thể thực tế, zip lồng nhau)
│   ├── model.py            # Section / Patch
│   ├── engine.py           # áp patch: glob target, component target, GOTO,
│   │                       #   biến MATCH_ASSIGN, idempotency, backup, dry-run,
│   │                       #   MERGE tái cấu trúc ID qua public.xml,
│   │                       #   6 khối hiện đại SET_BOOL/INIT/HOOK_SCRIPT/
│   │                       #   TRACE/API_LOG/REMOTE_CONFIG
│   ├── audit.py            # 15 lớp kiểm tra kiến trúc + nâng cấp tự động
│   ├── optimizer.py        # gộp/dedupe/xung đột/năng lực/độ tương đồng
│   ├── combo.py            # gộp combo các patch hỗ trợ nhau
│   ├── advisor.py          # coverage, suggest, roadmap
│   ├── simulate.py         # mô phỏng toàn diện (tự sinh mẫu, chấm hiệu quả)
│   ├── indexer.py          # index.json + report.md
│   └── cli.py              # giao diện dòng lệnh
├── tests/run_tests.py      # bộ tự kiểm tra (52 bài)
├── index.json / report.md  # sinh ra khi chạy index/audit
├── upgraded/               # patch đã nâng cấp (sinh ra khi chạy upgrade)
├── optimized/              # patch gộp tối ưu (sinh ra khi chạy optimize)
├── simulation_report.md    # kết quả mô phỏng toàn diện
└── EVALUATION.md           # tự đánh giá mức đạt nhu cầu
```

## Logic "thông minh" đã cài sẵn

- **Parser bền**: khối không thẻ đóng, `TARGET: [LAUNCHER_ACTIVITIES]`,
  BOM/CRLF, tên entry zip không phải UTF-8, zip lồng nhau (Installocation).
- **Engine an toàn**: sao lưu trước khi sửa (`.patchx/backup/...`), ghi trạng
  thái `.patchx/state.json` để không áp trùng, `--dry-run` xem trước, chặn
  đường dẫn `..`, chặn vòng lặp GOTO.
- **Component target**: `[LAUNCHER_ACTIVITIES]` tự dò manifest → smali.
- **An toàn đường dẫn**: chặn ADD_FILES với TARGET tuyệt đối/chứa `..`; `TARGET: /` được coi là gốc cây (tương thích APK Editor); non-EXTRACT cần đường dẫn tệp.
- **Không lặp tiền tố EXTRACT**: entry trong zip đã chứa TARGET (vd
  `TARGET: smali`, entry `smali/apkeditor/...`) được bỏ phần trùng trước khi
  nối — tránh tạo `smali/smali/...` khiến apktool báo class trùng.
- **Chống treo**: phát hiện vòng lặp GOTO theo chu trình thực sự (patch 27.000+ khối như RES-ID chạy bình thường, không đếm bước cứng).
- **Lọc regex an toàn**: `_literal_hint` bỏ qua regex nhiều nhánh `|` và lớp ký tự `\d/\w/\s` — không lọc nhầm tệp.
- **EXECUTE_DEX an toàn**: `--dex-runner` chạy không qua shell, chặn ký tự shell, phân giải lệnh tồn tại, giới hạn thời gian (`--dex-timeout`).
- **Trùng lặp**: mọi bản ghi scan có `sha256` (theo patch.txt) + `dupe_id` nhóm trùng.
- **Mô hình ứng dụng (Đợt A)**: `model` tách nhận diện khỏi thay đổi; ghi
  dấu vân tay hành vi (kiểu, chuỗi lệnh, nhánh, hằng số, lời gọi), cạnh gọi,
  nguồn dữ liệu và điểm quyết định. Dữ liệu này chỉ làm bằng chứng cho
  plan/preflight, không tự áp patch.
- **Kế hoạch ngữ nghĩa (Đợt B)**: `semantic-plan` dùng schema
  `patchx.semantic-plan/v1`, gồm `goal`, `targets.conditions`,
  `operations`, `verification`. Chỉ khi mọi target đạt `min_score` mới trả
  `READY_FOR_PREFLIGHT`; lệnh không gọi engine hay sửa APK.
- **Kế hoạch ngữ nghĩa V2**: `patchx.semantic-plan/v2` dùng
  `selector.all` + `near_entry`, `policy.min_score/max_accepted` và bắt buộc
  `on_ambiguous: "STOP"`. Nó chỉ nhận `patchx.app-model/v2`; verdict
  `AMBIGUOUS_TARGET` hoặc `INSUFFICIENT_EVIDENCE` luôn dừng trước preflight.
- **Kho tri thức V2**: `patchx.knowledge-record/v2` chỉ nhận record
  `verified=true` có đủ kết quả preflight/validate/build/runtime. Lệnh
  `knowledge query --v2` xếp hạng exact/structural/semantic để tham chiếu;
  không tự chọn mục tiêu và vẫn phải chạy semantic-plan + preflight.
- **Bản đồ phiên bản V2**: `diffapk.match_app_models_v2` ghép method theo
  identity exact/structural/semantic; trường hợp nhiều ứng viên hoặc thiếu
  bằng chứng luôn là `unknown`, không bị cưỡng ép ghép.
- **Data-flow V2**: `remote-map --dataflow` mỗi method mang `primary_role`
  (decision/sink/transform/source), `data_type` và `confidence`; đường đi từ
  điểm quyết định tới sink được giữ làm bằng chứng, không sinh thay đổi.
- **Nghiệm thu V2**: `acceptance` đo theo tiêu chí trong
  `de xuat phuong an/đề xuất.txt` — tái lập model, tái nhận diện sau
  obfuscation, dương tính giả ở `READY_FOR_PREFLIGHT`, mơ hồ và không tự tin
  đều phải bị chặn; suite còn khóa an toàn thực thi: các bước V2 chỉ-đọc
  không được gọi `Engine.apply`.
- **Gộp thông minh**: gộp patch cùng nhóm/cùng target; gộp trùng khối; xung
  đột (cùng MATCH khác REPLACE) tự tách riêng.
- **Combo theo họ + class-link (v2)**: `--auto` tự xếp patch vào họ chức năng
  hẹp (license, signature, google, shell, trace, ads, id-spoof, ẩn danh, mạng,
  theme, splash, toast, screen, quyền, lưu trữ, cài đặt, api, token) và gộp
  theo họ; patch cô lập được ghép qua class-link (A cung cấp class, B dùng).
  KHÔNG gộp chéo họ qua chuỗi năng lực — tránh combo rác.
- **Engine multi-pass**: quét tối đa 3 lượt — khối sau tạo chuỗi cho khối
  trước khớp ở lượt sau; đã kiểm chứng 25/25 combo áp thành công và idempotent.
- **6 khối thực thi hiện đại**:
  - `SET_BOOL`: đổi literal boolean (true/false/0x0/0x1/1/0) trong vùng khớp.
  - `INIT`: chèn `CODE` vào đầu thân `METHOD` (mặc định `onCreate`) của target.
  - `HOOK_SCRIPT`: ghi asset smali + chèn `invoke-static` gọi `ENTRY`.
  - `TRACE` / `API_LOG`: chèn `Log.d` quanh dòng khớp, tự cấp 2 thanh ghi tạm.
  - `REMOTE_CONFIG`: sinh `Lpatchx/RemoteConfig;` chứa `CONFIG_URL` + chèn
    init; khóa `FORCE` ép giá trị boolean tại MỌI điểm đọc
    (`sget/iget-boolean` → `const/4`) — điểm sau lớp giải mã, bất chấp payload
    mã hóa; idempotent theo từng flag.
- **Tìm sâu**: coverage quét toàn cây, đề xuất biến thể hoa thường/khoảng
  trắng, báo chuỗi xuất hiện ngoài target.
- **Roadmap**: xếp hạng patch theo tỷ lệ khớp trên APK thật.

## Khối thực thi hiện đại — mẫu nhanh

```txt
[SET_BOOL]
TARGET: smali/com/demo/Flags.smali
MATCH: const/4 v0, 0x0
REGEX: false
VALUE: 0x1
[/SET_BOOL]

[INIT]
TARGET: [LAUNCHER_ACTIVITIES]
METHOD: onCreate
CODE:
const-string v0, "patchx-init-ok"
[/INIT]

[HOOK_SCRIPT]
SOURCE: Hook.smali
TARGET: [LAUNCHER_ACTIVITIES]
METHOD: onCreate
ENTRY: onCreate
[/HOOK_SCRIPT]

[TRACE]
TARGET: smali/com/demo/MainActivity.smali
MATCH: return-void
REGEX: false
TAG: PatchXTest
[/TRACE]

[API_LOG]
TARGET: smali/com/demo/Api.smali
MATCH: https://
REGEX: false
TAG: ApiTest
[/API_LOG]

[REMOTE_CONFIG]
CONFIG_URL: https://config.example.com/patchx.json
TARGET: [LAUNCHER_ACTIVITIES]
METHOD: onCreate
FORCE:
# Lcls;->fld:Z = true|false — mỗi dòng một flag
[/REMOTE_CONFIG]
```

## Theo dõi mã điều khiển hành vi từ xa (remote trace)

- `python3 patchx remote-map <cây_apk> -o remote_flags.json` — quét field
  boolean + AtomicBoolean + mọi điểm đọc/ghi, in flag nổi bật nhất; thêm
  `--flow` để dựng bản đồ luồng quyết định/dữ liệu.
- `python3 patchx remote-patch remote_flags.json --set 'Lcls;->fld:Z = true'
  -o force.zip` — sinh patch `[REMOTE_CONFIG]` kèm `FORCE` ép giá trị tại
  điểm READ; cũng nhận `--force overrides.json` (dạng `{"Lcls;->fld:Z": true}`).
- `hook_remote_data_control/patch.txt` — ví dụ đầy đủ: `DataGuard` (log
  `patchx-remote-control`), nối điểm chặn `ConfigKt->ui`, `TRACE` ghi
  `SharedPreferences`/`OkHttp`, vô hiệu hóa 7 SDK analytics, `FORCE` flag.

## Patch chuỗi .rodata bằng Frida (ro.data runtime)

- `python3 patchx rodata-find lib/x86_64/libnative-lib.so --string
  "https://api.old-server.com/v1"` — tìm RVA của chuỗi trong `.rodata`.
- `python3 patchx rodata-patch ... --string CHUỖI --new CHUỖI_MỚI --mode
  inline` — sinh script Frida ghi đè chuỗi trên RAM khi app chạy (không
  sửa file gốc, không giới hạn độ dài).
- `--mode pointer --ptr-offset RVA` — đổi con trỏ tới chuỗi mới cấp phát
  trong RAM: an toàn với dữ liệu xung quanh, độ dài vô hạn.
- `--runtime-scan` — không cần RVA tĩnh: quét RAM module tìm chuỗi gốc rồi
  ghi inline (hợp bản .so đổi/obfuscate).
- `python3 patchx rodata-apply FILE.SO --string CHUỖI --new CHUỖI_MỚI` —
  chèn chuỗi trực tiếp vào file `.so` (backup trước khi ghi; chuỗi mới phải
  ngắn hơn hoặc bằng chuỗi cũ, trừ `--allow-overflow`).
- **Bộ bypass riêng**: `patchx_core/rodata_bypass/` (module riêng) +
  `rodata_bypass_main.py` (main hiển thị riêng) — 2 thành phần tách biệt:
  luồng TĨNH (`--flow static`, patch file) và luồng ĐỘNG (`--flow dynamic`,
  Frida RAM). Chạy: `python3 rodata_bypass_main.py FILE.SO --flow static
  --string CHUỖI --new CHUỖI_MỚI`.
- Chi tiết: `HUONG_DAN_BEHAVIOR_FRIDA.txt` mục 12 + 13 + 14.

## Giới hạn (được báo rõ, không tự sửa)

- `EXECUTE_DEX`: mặc định bỏ qua; muốn chạy dùng `--dex-runner "lệnh"`.
- `MERGE`: tái cấu trúc ID tài nguyên chỉ hoạt động khi có `public.xml`
  trong zip và trong cây APK.
- Regex lỗi/không khớp: chỉ cảnh báo, không tự sửa nội dung (tránh hỏng patch).
- Bản nâng cấp sinh ra trong `upgraded/` — bộ sưu tập gốc không bị sửa.
