# Cấu hình

Sao chép `app.example.ini` thành `app.ini` trước khi chạy ứng dụng. Parser hỗ
trợ dòng trống, comment bắt đầu bằng `#` hoặc `;`, và cú pháp `key = value`.

Giai đoạn 1 chỉ phục vụ tuần tự một client. Các cấu hình concurrency được để
dành cho giai đoạn 2 và không xuất hiện trong file này.

## `[server]`

- `bind_address`: địa chỉ server bind, mặc định `0.0.0.0`.
- `port`: cổng lắng nghe, từ `1` đến `65535`.
- `storage_directory`: thư mục gốc lưu file hoàn chỉnh trên server.

## `[client]`

- `server_address`: hostname hoặc IP của server.
- `server_port`: cổng server, từ `1` đến `65535`.
- `connect_timeout_ms`: timeout kết nối (ms), từ `1` đến `300000`.
- `download_directory`: thư mục lưu file tải xuống ở client.

## `[network]`

- `max_payload_bytes`: payload tối đa, từ `1` byte đến `16777216` byte
  (16 MiB).
- `chunk_size_bytes`: kích thước dữ liệu mỗi chunk, từ `4096` đến `65536` byte.

`max_payload_bytes` phải lớn hơn hoặc bằng `chunk_size_bytes + 8`, vì payload
`FILE_CHUNK` gồm offset 8 byte và dữ liệu chunk.

Parser cố ý từ chối section/key lạ, key bị lặp, số ngoài phạm vi và cấu hình
chunk không tương thích để phát hiện lỗi ngay khi khởi động.
