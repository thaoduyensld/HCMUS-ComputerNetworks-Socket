# Kiến trúc giai đoạn 1

## 1. Phạm vi

Giai đoạn 1 xây dựng hai executable TCP:

- `HcmusSocketClient`: giao diện dòng lệnh với `LIST`, `UPLOAD`, `DOWNLOAD`.
- `HcmusSocketServer`: lắng nghe, phục vụ tuần tự một client và quản lý storage.

Server chỉ xử lý một client tại một thời điểm. Thread pool, nhiều client đồng
thời, login, resume và throttling thuộc giai đoạn 2.

## 2. Ranh giới module

```text
Client ----\
            >---- Common
Server ----/
```

### `Common`

Chứa code thuần C++ dùng ở cả hai phía:

- Protocol constants, opcode và error code.
- Connection preface và frame codec.
- `send_all` và `receive_exact`.
- Chuyển đổi network byte order.
- File metadata và payload serialization.
- SHA-256 abstraction.
- Config và validation.
- Filename validation dùng chung.

`Common` không được phụ thuộc `Client` hoặc `Server`.

### `Client`

Chịu trách nhiệm:

- Đọc config và kết nối server.
- Thực hiện connection preface.
- Parse đúng ba lệnh người dùng.
- Điều phối luồng LIST, upload và download.
- Ghi download vào file `.part`.
- Hiển thị lỗi và kết quả checksum.

Client không được truy cập trực tiếp storage của Server.

### `Server`

Chịu trách nhiệm:

- Khởi tạo TCP listener.
- Accept và xử lý tuần tự một client.
- Kiểm tra connection preface.
- Quản lý máy trạng thái phiên.
- Dispatch request theo opcode.
- Quản lý storage root và file `.part`.
- Ghi log phiên, tốc độ và kết quả checksum.
- Sau khi client đóng, giải phóng tài nguyên và quay lại accept.

## 3. Luồng phụ thuộc

- `Client` và `Server` chỉ giao tiếp qua protocol v1.
- Không include header trực tiếp giữa `Client` và `Server`.
- Kiểu dữ liệu đi qua mạng phải nằm trong `Common`.
- Business rule chỉ thuộc một phía không đưa vào `Common`.
- Thay đổi wire format phải cập nhật `docs/PROTOCOL.md` trước.

## 4. Trạng thái phiên Server

```text
CONNECTED
    |
    v
PREFACE_VALIDATED
    |
    v
IDLE ---------------------> CLOSING
 |  \
 |   \--------------------> SENDING_DOWNLOAD
 |
 \------------------------> RECEIVING_UPLOAD
```

Mỗi phiên chỉ có một transfer hoạt động. Sau khi request hoàn tất hoặc gặp lỗi
nghiệp vụ có thể phục hồi, phiên quay lại `IDLE`.

## 5. Storage

- Server chỉ thao tác bên trong `server.storage_directory`.
- Upload được ghi vào file `.part`.
- File `.part` không xuất hiện trong LIST.
- File trùng tên bị từ chối.
- File chỉ được đổi sang tên chính sau khi kích thước và SHA-256 khớp.
- Trong giai đoạn 1, file `.part` bị xóa khi transfer thất bại hoặc kết nối đứt.

## 6. Kế thừa sang giai đoạn 2

Giai đoạn 2 giữ nguyên:

- Frame codec.
- File chunk payload.
- SHA-256 streaming.
- Config foundation.
- Client/Server handler boundaries.

Giai đoạn 2 mở rộng server session bằng concurrency, gán `USER_ID`, namespace
riêng và resume qua offset. Không viết lại protocol transport từ đầu.

### Registry session và username

`server/registry.py` cung cấp `ActiveSessionRegistry` dùng chung cho các worker:

- Đăng ký một session ngay khi worker nhận quyền sở hữu socket.
- Claim username theo thao tác nguyên tử; hai session không thể giữ cùng tên.
- Cấp `USER_ID` khác `0` và tái sử dụng ID đã giải phóng theo thứ tự nhỏ nhất.
- Giải phóng session, username và `USER_ID` trong `finally` khi worker kết thúc.
- Trả snapshot bất biến để quan sát mà không làm lộ cấu trúc dữ liệu nội bộ.

`ServerSession` nhận tham chiếu registry và `registry_session_id` để luồng LOGIN
giai đoạn 2 có thể claim username mà không tự quản lý lock hoặc ID allocator.
