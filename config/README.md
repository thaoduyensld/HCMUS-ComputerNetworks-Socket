# Cấu hình

Sao chép `app.example.ini` thành `app.ini` trước khi chạy ứng dụng. Parser hỗ
trợ dòng trống, comment bắt đầu bằng `#` hoặc `;`, và cú pháp `key = value`.

File này chứa schema cấu hình dùng chung cho protocol v2. Branch protocol/config
chỉ đọc và kiểm tra giá trị; hành vi giới hạn client, throttling và dọn partial
theo TTL được triển khai bởi các module tương ứng.

## `[server]`

- `bind_address`: địa chỉ server bind, mặc định `0.0.0.0`.
- `port`: cổng lắng nghe, từ `1` đến `65535`.
- `storage_directory`: thư mục gốc lưu file hoàn chỉnh trên server.
- `max_clients`: số phiên client được phục vụ đồng thời, từ `1` đến `1000`;
  mặc định `10`. Kết nối vượt giới hạn nhận lỗi `SERVER_BUSY`.
- `partial_ttl_seconds`: thời gian giữ một cặp `.part`/`.part.meta`, phải từ
  `0` giây trở lên. Giá trị `0` tắt cleanup tự động. Server dọn các cặp hết hạn
  khi khởi động và kiểm tra lại đúng filename trước mỗi Upload mới.

## `[client]`

- `server_address`: hostname hoặc IP của server.
- `server_port`: cổng server, từ `1` đến `65535`.
- `connect_timeout_ms`: timeout kết nối (ms), từ `1` đến `300000`.
- `download_directory`: thư mục lưu file tải xuống ở client.

## `[network]`

- `max_payload_bytes`: payload tối đa, từ `1` byte đến `16777216` byte
  (16 MiB).
- `chunk_size_bytes`: kích thước dữ liệu mỗi chunk, từ `4096` đến `65536` byte.
- `bandwidth_limit_kib_per_second`: giới hạn băng thông mỗi client, phải từ `0`
  KiB/s trở lên; `0` nghĩa là không giới hạn.

## `[auth]`

- `max_username_bytes`: độ dài username tối đa theo UTF-8, từ `1` đến `32` byte.

`max_payload_bytes` phải lớn hơn hoặc bằng `chunk_size_bytes + 8`, vì payload
`FILE_CHUNK` gồm offset 8 byte và dữ liệu chunk.

Ví dụ giới hạn mỗi client ở khoảng 500 KiB/s với burst một chunk:

```ini
[network]
bandwidth_limit_kib_per_second = 500
```

Parser cố ý từ chối section/key lạ, key bị lặp, số ngoài phạm vi và cấu hình
chunk không tương thích để phát hiện lỗi ngay khi khởi động.
