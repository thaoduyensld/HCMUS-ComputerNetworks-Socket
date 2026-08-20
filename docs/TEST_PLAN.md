# Kế hoạch kiểm thử bản nộp cuối

## 1. Mục tiêu

Xác minh protocol v2, truyền file streaming, checksum, nhiều client, namespace,
resume, throttling, logging, desktop UI và khả năng phục hồi sau lỗi. Mỗi lần
chốt release phải ghi commit SHA, hệ điều hành, phiên bản Python và kết quả test.

## 2. Quality gate tự động

Từ môi trường sạch:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q src scripts
```

CI phải pass trên Windows và Ubuntu với Python 3.11–3.12. Test symlink được phép
skip khi hệ điều hành hoặc quyền hiện tại không hỗ trợ tạo symlink.

## 3. Ma trận tự động

| Nhóm | Nội dung bắt buộc | Test chính |
|---|---|---|
| Config | Schema nghiêm ngặt, range, key/section lạ | `test_config.py` |
| Framing | Preface, partial recv/send, length, opcode | `test_framing.py` |
| Message | Encode/decode mọi payload, UTF-8, giới hạn | `test_messages.py` |
| Protocol | Opcode, error code, user ID, payload limit | `test_protocol.py` |
| Auth/session | LOGIN, username trùng/sai, lifecycle | `test_auth_session.py`, `test_client_session.py` |
| LIST | Namespace, sorting, file partial, payload lớn | `test_server_listing.py`, `test_client_listing.py` |
| Upload | Streaming, offset, checksum, publish, lỗi I/O | `test_server_upload.py`, `test_client_upload.py` |
| Download | Streaming, resume, checksum, destination | `test_server_download.py`, `test_client_download.py` |
| Concurrency | Nhiều worker, capacity, cleanup | `test_server_concurrency.py`, `test_server_cleanup.py` |
| Locking | Cùng file/cùng namespace và namespace khác | `test_filename_locks.py` |
| Resume | Partial metadata, ngắt và reconnect TCP thật | `test_partial_transfer.py`, `test_resume_e2e.py` |
| Throttling | Token bucket, quota độc lập, tích hợp session | `test_throttling.py` |
| Logging | JSONL schema, thread safety, failure status | `test_server_logger.py`, `test_server_logging_integration.py` |
| API/CLI | Dispatch, validation, đóng session | `test_client_api.py`, `test_client_app.py`, `test_client_commands.py` |
| UI | Worker, connection form, file browser, validation | `test_ui_worker.py`, `test_ui_connection.py`, `test_ui_file_listing.py` |
| End-to-end | LIST/Upload/Download/checksum qua TCP | `test_phase1_end_to_end.py`, `test_download_end_to_end.py` |

## 4. Kích thước và loại file

Phải kiểm tra cả Upload và Download cho:

| Loại | Kích thước |
|---|---:|
| Rỗng | 0 byte |
| Nhỏ | 512 byte |
| Sát biên chunk | 32.767, 32.768 và 32.769 byte |
| Trung bình | 10 MiB |
| Lớn | 120 MiB |
| Nhị phân | Chứa đủ kiểu byte, bao gồm `0x00` |

File test lớn được sinh trong `runtime/`, không commit và không đưa vào ZIP.

## 5. Acceptance test thủ công

### A. Khởi động và thao tác cơ bản

1. Copy `config/app.example.ini` thành `config/app.ini`.
2. Chạy server và một client CLI.
3. LOGIN, LIST thư mục rỗng, Upload một file, LIST lại và Download.
4. So sánh SHA-256 giữa file nguồn, ACK server và file tải xuống.
5. Thoát client rồi kết nối lại cùng username.

Kết quả: không crash, trạng thái rõ ràng, file và checksum trùng khớp.

### B. Desktop UI

1. Mở UI ở kích thước mặc định, thu nhỏ cửa sổ và bật display scaling.
2. Kết nối, đổi List/Grid, Refresh, Upload, Download và Cancel.
3. Chuyển Light/Dark, đổi List/Grid và kiểm tra trang Settings/About.
4. Thử chọn file nguồn đã bị xóa và destination đã tồn tại.

Kết quả: UI không treo; progress, cancel, status và thông báo lỗi luôn nhìn thấy;
không ghi đè file local ngoài ý muốn.

### C. Nhiều client và namespace

1. Mở ít nhất hai client với username khác nhau.
2. Upload cùng basename nhưng nội dung khác nhau.
3. LIST và Download ở từng client.
4. Kết nối thêm client vượt `max_clients` và thử username đang được dùng.

Kết quả: namespace được cô lập; nhận `SERVER_BUSY` và `USERNAME_IN_USE` đúng.

### D. Resume và lỗi mạng

1. Ngắt Upload/Download ở khoảng 30%, 50% và 70%.
2. Reconnect cùng username và truyền lại cùng file.
3. Thử metadata hoặc file nguồn không còn khớp partial.

Kết quả: resume đúng offset, checksum cuối khớp; mismatch không publish file.

## 6. Demo và benchmark có thể tái lập

```powershell
python scripts/benchmark_phase1.py
python scripts/phase2_large_resume.py
python scripts/phase2_load_resilience.py
python scripts/phase2_throttling_benchmark.py
```

- Benchmark file: 512 byte, 10 MiB và 120 MiB.
- Load/resilience: 10 client, client thứ 11, peer lỗi và 100 vòng lifecycle.
- Resume: file lớn, ngắt giữa transfer và xác minh SHA-256.
- Throttling: ít nhất 5 giây steady state, sai số tối đa theo tham số tolerance.

## 7. Tiêu chí release

- Toàn bộ test không skip ngoài giới hạn nền tảng đã giải thích.
- `git diff --check` không báo whitespace error.
- Config mẫu load được và cả ba CLI entry point khởi động được.
- Không có secret, config cá nhân, log, cache, binary hoặc file test lớn trong
  danh sách Git/ZIP.
- README và lệnh demo khớp code tại commit release.
- Upload/Download file lớn không làm bộ nhớ tăng tuyến tính theo kích thước file.
- Server tiếp tục nhận client sau peer lỗi và giải phóng toàn bộ worker/registry.
- Commit SHA/tag trong báo cáo trùng với source dùng để quay video và nộp bài.
