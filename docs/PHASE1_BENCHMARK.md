# Kết quả benchmark Giai đoạn 1

Ngày chạy: 06/08/2026

Môi trường: Windows, Python 3.12.7, loopback TCP `127.0.0.1`

Chunk size: 32.768 byte

Max payload: 1.048.576 byte

Lệnh chạy:

```powershell
python scripts/benchmark_phase1.py
```

## Kết quả

| Kích thước | Upload (giây) | Upload (KiB/s) | Peak Upload | Download (giây) | Download (KiB/s) | Peak Download |
|---:|---:|---:|---:|---:|---:|---:|
| 512 byte | 0,031367 | 15,940 | 184.796 byte | 0,012443 | 40,182 | 187.255 byte |
| 10 MiB | 0,127677 | 80.202,197 | 416.509 byte | 0,137595 | 74.421,255 | 417.242 byte |
| 120 MiB | 1,539824 | 79.801,349 | 417.340 byte | 1,611950 | 76.230,671 | 418.017 byte |

SHA-256 khớp cho cả file nguồn, file được server lưu và file Download ở cả ba
kích thước. Peak allocation được đo bằng `tracemalloc` cho toàn process
benchmark; giá trị gần như không đổi giữa 10 MiB và 120 MiB, phù hợp với thiết
kế streaming theo chunk và không load toàn bộ file vào RAM.

Các tốc độ trên là loopback nội bộ nên chỉ dùng để so sánh implementation và
chứng minh quy trình đo. Báo cáo/demo trên hai máy thật nên chạy lại cùng script
và ghi thêm thông tin CPU, ổ đĩa và kết nối mạng.

## Checksum

| Kích thước | SHA-256 |
|---:|---|
| 512 byte | `110009dcee21620b166f3abfecb5eff7a873be729d1c2d53822e7acc5f34eb9b` |
| 10 MiB | `aecf3c2ab8aca74852bca07b54136cecb3fdafdc35540068ed952c0b89538e0d` |
| 120 MiB | `404133e58cb36f36999c9b377c2770834cc04324393f9eedf8cb45ce6efb2783` |

## Tái tạo kết quả

Script mặc định tạo một thư mục mới dưới `runtime/`, sinh file theo streaming,
khởi động server trên một cổng loopback tạm, chạy Upload và Download bằng
`ClientSession`, kiểm tra checksum rồi ghi `benchmark.json`. Các file lớn và
log runtime bị Git bỏ qua và không được commit.
