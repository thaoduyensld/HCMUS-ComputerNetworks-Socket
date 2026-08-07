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
- `max_clients`: số client tối đa, phải từ `1` trở lên, mặc định `10`.
- `partial_ttl_seconds`: thời gian giữ partial file, phải từ `0` giây trở lên.

## `[client]`

- `server_address`: hostname hoặc IP của server.
- `server_port`: cổng server, từ `1` đến `65535`.
- `connect_timeout_ms`: timeout kết nối (ms), từ `1` đến `300000`.
- `download_directory`: thư mục lưu file tải xuống ở client.

## `[network]`

- `max_payload_bytes`: payload tối đa, từ `1` byte đến `16777216` byte
  (16 MiB).
- `chunk_size_bytes`: kích thước dữ liệu mỗi chunk, từ `4096` đến `65536` byte.
- `bandwidth_limit_bytes_per_second`: giới hạn tốc độ cho mỗi client, tính theo
  byte/giây. `0` nghĩa là không giới hạn; giá trị tối đa là `1073741824`.
- `bandwidth_burst_bytes`: dung lượng burst của Token Bucket. Phải bằng `0` khi
  không giới hạn; khi bật giới hạn phải ít nhất bằng `chunk_size_bytes` và không
  vượt quá `16777216` byte.
- `bandwidth_limit_kib_per_second`: giới hạn băng thông mỗi client, phải từ `0`
  KiB/s trở lên; `0` nghĩa là không giới hạn.

## `[auth]`

- `max_username_bytes`: độ dài username tối đa theo UTF-8, từ `1` đến `32` byte.

`max_payload_bytes` phải lớn hơn hoặc bằng `chunk_size_bytes + 8`, vì payload
`FILE_CHUNK` gồm offset 8 byte và dữ liệu chunk.

Ví dụ giới hạn mỗi client ở khoảng 500 KiB/s với burst một chunk:

```ini
[network]
bandwidth_limit_bytes_per_second = 512000
bandwidth_burst_bytes = 32768
```

Parser cố ý từ chối section/key lạ, key bị lặp, số ngoài phạm vi và cấu hình
chunk không tương thích để phát hiện lỗi ngay khi khởi động.
