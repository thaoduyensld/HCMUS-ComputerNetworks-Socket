# Kiến trúc bản nộp cuối — Protocol v2

## 1. Tổng quan

Hệ thống gồm một TCP server và hai giao diện client dùng chung lớp API:

```text
CLI client ──┐
             ├── ClientApi / ClientSession ── TCP protocol v2 ── Server
Desktop UI ──┘                                              ├── Registry
                                                            ├── Storage
                                                            ├── Filename locks
                                                            └── JSONL logger
```

Code sử dụng Python 3.11+, thư viện chuẩn và layout `src/`. Protocol là nhị
phân, có framing rõ ràng và không phụ thuộc ranh giới của từng lần `send()` hay
`recv()`.

## 2. Ranh giới module

### Nền tảng dùng chung

- `config.py`: dataclass cấu hình và parser INI nghiêm ngặt.
- `protocol.py`: version, opcode, error code và giới hạn wire format.
- `framing.py`: connection preface, frame header, `send_all()` và
  `recv_exact()`.
- `messages.py`: encode/decode payload có kiểm tra độ dài và UTF-8.
- `throttling.py`: token bucket thread-safe theo từng session.
- `common/partial_transfer.py`: metadata và kiểm tra file partial phục vụ resume.

Các module này không phụ thuộc UI và không truy cập trực tiếp storage của một
người dùng.

### Client

- `client/session.py`: kết nối, preface, LOGIN, request ID và lifecycle phiên.
- `client/listing.py`, `upload.py`, `download.py`: các workflow truyền file.
- `client/api.py`: API ổn định cho UI hoặc front end khác.
- `client/app.py`: giao diện dòng lệnh.

Client truyền file theo chunk. Upload đọc tuần tự từ nguồn; Download ghi vào
file partial trước khi xác nhận kích thước và SHA-256.

### Desktop UI

- `ui/app.py`: shell, điều phối màn hình và state ứng dụng.
- `connection_view.py`, `file_view.py`, `transfer_view.py`, `settings_view.py`:
  các view độc lập.
- `worker.py`: hàng đợi tác vụ nền và sự kiện trả về UI thread.

Tkinter chỉ được cập nhật trên main thread. Socket và file I/O chạy trong
`BackgroundWorker`, nhờ đó cửa sổ không bị treo khi transfer. Mỗi thời điểm UI
chỉ phát một tác vụ file; cancel đóng session hiện tại để ngắt I/O an toàn.

### Server

- `server/app.py`: listener, admission control và vòng đời worker.
- `server/session.py`: state machine, LOGIN và dispatch opcode.
- `server/listing.py`, `upload.py`, `download.py`: nghiệp vụ storage.
- `server/registry.py`: session, username và user ID đang hoạt động.
- `server/filename_locks.py`: khóa độc quyền theo namespace/filename.
- `server/cleanup.py`: dọn partial hết TTL.
- `server/logger.py`: JSON Lines logger dùng chung, thread-safe.

## 3. Kết nối và xác thực

Một kết nối hợp lệ đi theo chuỗi:

```text
TCP CONNECT
  → Client preface
  → Server preface
  → LOGIN(username, request_id)
  → ACK(user_id)
  → LIST / UPLOAD / DOWNLOAD
  → DISCONNECT hoặc đóng socket
```

Trước LOGIN, frame phải dùng `USER_ID = 0`. Sau LOGIN, client dùng user ID do
server cấp. Registry claim username bằng thao tác nguyên tử nên hai phiên đang
hoạt động không thể dùng cùng username.

## 4. Mô hình đồng thời

Server có một listener và tạo một worker thread cho mỗi kết nối được chấp nhận.
`BoundedSemaphore` giới hạn số worker theo `server.max_clients`. Kết nối vượt
giới hạn được hoàn tất đủ handshake để nhận lỗi `SERVER_BUSY` thay vì bị đóng
không rõ nguyên nhân.

State dùng chung được bảo vệ như sau:

- Registry dùng lock cho session, username và user ID.
- Filename lock cô lập từng `(namespace, filename)`.
- Logger dùng một lock chung cho write, flush và close.
- Mỗi session có token bucket riêng; không chia quota giữa client.
- Shutdown đóng listener, xử lý hoặc hủy socket đang hoạt động rồi join worker
  trước khi đóng logger.

## 5. Namespace và storage

Mỗi username được ánh xạ ổn định sang một thư mục con an toàn dưới
`server.storage_directory`. LIST, Upload, Download chỉ thao tác trong namespace
đó; basename, separator, `..`, tên quá dài và đường dẫn thoát root đều bị từ
chối.

Upload không ghi trực tiếp lên file đích:

1. Tạo/kiểm tra cặp file partial và metadata.
2. Thương lượng offset resume.
3. Ghi các chunk liên tục và kiểm tra offset.
4. So sánh kích thước cùng SHA-256.
5. Publish nguyên tử sang tên hoàn chỉnh.

Download cũng thương lượng offset dựa trên partial local. File hoàn chỉnh chỉ
được công nhận sau khi client kiểm tra đủ byte và SHA-256.

## 6. Framing và protocol

Connection preface gồm magic, version và reserved bytes. Mỗi frame gồm length,
opcode, user ID và payload. Tất cả integer nhiều byte dùng network byte order.
Payload bị giới hạn trước khi cấp phát; file chunk mặc định 32 KiB và luôn mang
offset 8 byte.

`docs/PHASE2_PROTOCOL.md` là đặc tả chuẩn cho bản nộp cuối. `docs/PROTOCOL.md`
ghi lại protocol nền tảng của Phase 1 và các điểm được Phase 2 mở rộng.

## 7. Resume và chịu lỗi

- Mất kết nối không làm publish file chưa hoàn chỉnh.
- Partial hợp lệ được giữ để reconnect cùng username và resume.
- Metadata mismatch, offset sai hoặc checksum sai tạo lỗi protocol rõ ràng.
- Partial quá TTL được dọn khi server khởi động và trước Upload liên quan.
- Lỗi ở một worker không làm listener hoặc worker khác dừng.
- Mọi socket, file handle, registry entry, filename lock và semaphore slot đều
  được giải phóng trong `finally`.

## 8. Giới hạn băng thông

Mỗi `ServerSession` có một `TokenBucket`. Khi giới hạn lớn hơn 0, Upload và
Download chỉ xử lý lượng byte được bucket cấp; sleep diễn ra ngoài lock. Burst
mặc định bằng một chunk. Giá trị `0` tắt throttling.

## 9. Bất biến quan trọng

- Không đọc toàn bộ file vào bộ nhớ.
- Không tin độ dài, offset, filename, username hoặc user ID từ peer.
- Không hiển thị file `.part` trong LIST.
- Không ghi đè file hoàn chỉnh đã tồn tại.
- Không publish nếu kích thước hoặc SHA-256 chưa khớp.
- Client không truy cập filesystem server ngoài protocol.
- UI thread không thực hiện socket/file I/O dài.
- Một lỗi session không được làm hỏng listener hay state client khác.
