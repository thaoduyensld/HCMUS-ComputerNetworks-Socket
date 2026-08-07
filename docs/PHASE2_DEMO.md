# Demo tải, resilience và throttling Giai đoạn 2

Hai script trong tài liệu này chạy server và client production trên TCP
loopback thật. Chúng không mock socket, framing, session, upload hoặc download.
Mỗi lần chạy tạo một thư mục riêng trong `runtime/` chứa log, dữ liệu tạm và báo
cáo JSON; không commit các artifact này.

## Chuẩn bị

Từ thư mục gốc của repository, cài project ở editable mode:

```powershell
python -m pip install -e .
```

Nếu chưa cài project, có thể dùng source tree trực tiếp:

```powershell
$env:PYTHONPATH = "$PWD\src"
```

## Resume end-to-end

```powershell
python -m pytest tests/test_resume_e2e.py -q
```

Sáu case này dùng client/server production và TCP loopback thật. Upload và
Download lần lượt bị ngắt cưỡng bức tại 30%, 50% và 70%, sau đó reconnect cùng
username, thương lượng offset Server, truyền phần còn lại và kiểm tra SHA-256.
Test cũng xác nhận `.part`/metadata được giữ khi mất kết nối và được dọn sau khi
publish thành công.

## Load và resilience

```powershell
python scripts/phase2_load_resilience.py
```

Cấu hình mặc định kiểm chứng:

- 10 client kết nối và `LIST` đồng thời;
- client thứ 11 nhận chính xác `SERVER_BUSY`;
- một peer gửi preface hỏng chỉ làm đóng session của chính nó;
- listener vẫn nhận client bình thường sau lỗi framing;
- 100 vòng connect, login, list và disconnect;
- registry và worker đều trở về 0;
- mọi dòng server log đều parse được thành JSON và logger không lỗi ghi.

Có thể đổi quy mô demo bằng `--clients` và `--cycles`. Kết quả được ghi vào
`load-resilience.json` trong đường dẫn in ở cuối chương trình. Script trả exit
code khác 0 ngay khi một tiêu chí không đạt.

## Benchmark throttling qua socket thật

```powershell
python scripts/phase2_throttling_benchmark.py
```

Mặc định script chạy 2 client đồng thời, mỗi client upload rồi download file 3
MiB với limit riêng 500 KiB/s. Mỗi chiều kéo dài hơn 5 giây để burst một chunk
không làm sai số ngắn hạn chi phối kết quả. Benchmark kiểm tra:

- upload và download đều đi qua TCP loopback và protocol v2 thật;
- hai client dùng hai token bucket/session độc lập;
- tốc độ trung bình từng client không vượt limit quá 10%;
- checksum nguồn, server ACK và file download trùng nhau.

Ví dụ đổi limit và kích thước:

```powershell
python scripts/phase2_throttling_benchmark.py `
  --clients 2 `
  --limit-kib-per-second 1024 `
  --size 6291456
```

`--size` tính bằng byte và phải đủ cho ít nhất 5 giây truyền ổn định ở limit đã
chọn. Báo cáo `throttling-benchmark.json` chứa wall time, tốc độ từng client,
trạng thái tolerance và checksum. Kết quả không đạt trả exit code 1.
