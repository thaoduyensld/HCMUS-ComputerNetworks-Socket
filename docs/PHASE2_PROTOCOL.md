# HCMUS Socket File Transfer Protocol v2

## 1. Trạng thái tài liệu

| Thuộc tính | Giá trị |
|---|---|
| Tên giao thức | HCMUS Socket File Transfer Protocol |
| Phiên bản wire | `2` |
| Giai đoạn áp dụng | Giai đoạn 2 |
| Trạng thái | Draft để cả nhóm review trước khi triển khai |
| Transport | TCP |
| Byte order | Network byte order (big-endian) |
| Mã hóa text | UTF-8 |
| Checksum | SHA-256 |
| Framing | Length-prefixed binary frame |
| Mô hình đồng thời | Bounded thread-per-client |

Tài liệu này là hợp đồng byte-level giữa Client và Server ở Giai đoạn 2. Các từ
**PHẢI**, **KHÔNG ĐƯỢC**, **NÊN** và **CÓ THỂ** diễn đạt mức độ bắt buộc của quy
tắc. Sau khi cả nhóm protocol freeze, mọi thay đổi wire format phải cập nhật tài
liệu, codec, Client, Server và test trong cùng một PR.

Protocol v2 kế thừa framing, chunking và checksum của protocol v1 trong
[`PROTOCOL.md`](PROTOCOL.md), đồng thời bổ sung:

- Nhiều client hoạt động đồng thời.
- LOGIN bằng username và gán `USER_ID` theo session.
- Namespace lưu trữ riêng theo username.
- Resume Upload và Download theo offset.
- Progress tracking phía Client.
- Throttling băng thông theo client.
- Giới hạn số client và phản hồi `SERVER_BUSY`.

## 2. Phạm vi và giới hạn

Protocol v2 hỗ trợ các command người dùng:

- `LOGIN <username>` được Client thực hiện tự động sau handshake; username lấy từ
  CLI hoặc config Client.
- `LIST`.
- `UPLOAD <local-path> [remote-filename]`.
- `DOWNLOAD <remote-filename>`.
- `DISCONNECT`.

Ngoài phạm vi Giai đoạn 2:

- Mật khẩu, xác thực danh tính mạnh và phân quyền quản trị.
- Mã hóa payload; nếu cần bảo mật phải đặt giao thức bên trong TLS.
- Nhiều transfer song song trên cùng một TCP connection.
- Chunk đến lệch thứ tự.
- Nén file, deduplication và delta transfer.
- Resume một phần file đã thay đổi nội dung nhưng giữ nguyên tên và kích thước.
- Đồng bộ namespace giữa nhiều tiến trình Server hoặc nhiều máy Server.

Username trong đồ án chỉ là định danh namespace, không phải bằng chứng xác thực.
Một người biết username có thể đăng nhập lại sau khi owner cũ logout vì đề bài
không yêu cầu password.

## 3. Kế thừa và tương thích với protocol v1

Protocol v2 giữ nguyên:

- `MAGIC = 0x48434D55` (`"HCMU"`).
- Header `LENGTH | OPCODE | USER_ID`.
- Ý nghĩa của `LENGTH`.
- Big-endian cho mọi số nguyên.
- Payload LIST, Upload, Download, chunk, checksum, ACK và ERROR.
- SHA-256 dạng 32 byte nhị phân.
- Opcode Giai đoạn 1 đã được cấp.

Protocol v2 thay đổi không tương thích ở các điểm:

- Preface dùng `VERSION = 2`.
- Sau preface, session ở `AUTHENTICATING`, chưa ở `IDLE`.
- Client PHẢI LOGIN trước mọi command file.
- `USER_ID` sau LOGIN PHẢI là ID được Server cấp, không còn luôn bằng `0`.
- File `.part` có thể được giữ lại sau mất kết nối để resume.
- Offset trong Upload và Download có thể khác `0`.

Client v1 và Server v2 không được phép giao tiếp như cùng một protocol. Hai bên
PHẢI từ chối preface khác version và đóng kết nối.

## 4. Nguyên tắc nhận dữ liệu TCP

TCP là byte stream, không giữ ranh giới giữa các lần `send()`. Bên nhận PHẢI:

1. Nhận chính xác 4 byte `LENGTH`.
2. Decode `LENGTH` bằng big-endian.
3. Kiểm tra giới hạn trước khi cấp phát payload.
4. Nhận chính xác thêm `LENGTH` byte.
5. Decode `OPCODE`, `USER_ID` và payload.
6. Validate payload theo opcode và state hiện tại.
7. Chỉ dispatch sau khi nhận đủ frame.

Một frame có thể bị chia qua nhiều lần `recv()` hoặc nhiều frame có thể đến trong
một lần `recv()`. TCP đóng giữa preface/header/payload làm stream mất đồng bộ;
session PHẢI đóng và không được cố đọc command tiếp theo.

## 5. Connection preface

Preface cố định 8 byte:

| Trường | Kích thước | Giá trị v2 |
|---|---:|---:|
| `MAGIC` | 4 byte | `0x48434D55` |
| `VERSION` | 2 byte | `0x0002` |
| `RESERVED` | 2 byte | `0x0000` |

Hex dump:

```text
48 43 4D 55  00 02  00 00
```

Handshake:

1. Client gửi preface v2.
2. Server nhận đủ 8 byte và validate cả ba trường.
3. Server echo đúng preface v2.
4. Client validate response.
5. Hai phía chuyển sang `AUTHENTICATING`.

Preface sai magic, version hoặc reserved là lỗi fatal; Server ghi log nếu có thể
và đóng socket mà không gửi business frame.

## 6. Cấu trúc frame

```text
+----------------+----------------+----------------+------------------+
| LENGTH         | OPCODE         | USER_ID        | PAYLOAD          |
| 4 byte         | 2 byte         | 2 byte         | biến đổi         |
+----------------+----------------+----------------+------------------+
```

### 6.1. `LENGTH`

`LENGTH` là `uint32`, không bao gồm chính 4 byte `LENGTH`:

```text
LENGTH = 2 + 2 + PAYLOAD_SIZE
PAYLOAD_SIZE = LENGTH - 4
TOTAL_FRAME_SIZE = 4 + LENGTH
```

Giá trị hợp lệ:

```text
4 <= LENGTH <= 4 + MAX_PAYLOAD_BYTES
```

### 6.2. `OPCODE`

`OPCODE` là `uint16`. Opcode quyết định schema payload và state hợp lệ.

### 6.3. `USER_ID`

`USER_ID` là `uint16` và có phạm vi `1..65535` sau LOGIN.

Quy tắc:

- Frame `LOGIN` từ Client PHẢI có `USER_ID = 0`.
- `ERROR` trước khi LOGIN PHẢI có `USER_ID = 0`.
- `ACK(LOGIN)` từ Server PHẢI đặt ID mới trong header `USER_ID`.
- Sau LOGIN, mọi frame hai chiều PHẢI dùng đúng ID của session.
- Client không được tự chọn hoặc thay đổi ID.
- ID chỉ có giá trị trong một TCP session và có thể được tái sử dụng sau khi
  session cũ đóng.
- Frame sau LOGIN có ID sai nhận `INVALID_USER_ID`, sau đó Server đóng session.

`USER_ID` không được dùng để suy ra đường dẫn. Server PHẢI ánh xạ ID sang username
đã lưu trong session rồi mới chọn namespace.

### 6.4. `PAYLOAD`

- Payload là byte thô có kích thước biến đổi.
- Text dùng UTF-8 strict; byte sequence UTF-8 sai bị từ chối.
- Chuỗi luôn có length prefix, không dùng byte `0x00` làm terminator.
- File data không được xử lý bằng hàm C-string hoặc `strlen()`.

## 7. Kiểu dữ liệu và giới hạn

| Kiểu | Kích thước | Mô tả |
|---|---:|---|
| `uint16` | 2 byte | Số nguyên không dấu big-endian |
| `uint32` | 4 byte | Số nguyên không dấu big-endian |
| `uint64` | 8 byte | Số nguyên không dấu big-endian |
| `utf8[n]` | `n` byte | UTF-8 không terminator |
| `bytes[n]` | `n` byte | Dữ liệu nhị phân thô |

| Giới hạn | Mặc định | Quy tắc |
|---|---:|---|
| Payload tối đa | 1 MiB | Cấu hình, kiểm tra trước cấp phát |
| File chunk | 32 KiB | Cấu hình trong khoảng 4–64 KiB |
| Tên file | 255 byte UTF-8 | Basename hợp lệ |
| Username | 32 byte UTF-8 | 1–32 byte sau encode |
| Client đồng thời | 10 | Cấu hình, không nhỏ hơn 10 khi demo/chấm |
| Transfer/session | 1 | Không multiplex transfer cùng connection |
| SHA-256 | 32 byte | Digest nhị phân |

## 8. Opcode

| Hex | Tên | Chiều | State hợp lệ | Ý nghĩa |
|---:|---|---|---|---|
| `0x0001` | `LOGIN` | C → S | `AUTHENTICATING` | Đăng nhập username |
| `0x0002` | `DISCONNECT` | C → S | `IDLE` | Logout và đóng session |
| `0x0010` | `FILE_LIST` | C → S | `IDLE` | Liệt kê file trong namespace |
| `0x0011` | `FILE_LIST_RESP` | S → C | LIST response | Danh sách file |
| `0x0012` | `FILE_UPLOAD` | C → S | `IDLE` | Mở mới hoặc resume Upload |
| `0x0013` | `FILE_DOWNLOAD` | C → S | `IDLE` | Mở mới hoặc resume Download |
| `0x0014` | `FILE_CHUNK` | Hai chiều | Transfer | Offset và file data |
| `0x0015` | `FILE_DELETE` | Dự phòng | — | Không bắt buộc trong GĐ2 |
| `0x0016` | `FILE_INFO` | S → C | Download | Metadata Download |
| `0x0017` | `FILE_CHECKSUM` | Hai chiều | Transfer | Final size và SHA-256 |
| `0x0020` | `ACK` | Hai chiều | Nhiều state | Xác nhận và next offset |
| `0x00FF` | `ERROR` | Hai chiều | Nhiều state | Mã lỗi có cấu trúc |

Opcode chưa triển khai hoặc không được định nghĩa nhận `UNSUPPORTED_OPCODE` nếu
stream vẫn đồng bộ.

## 9. LOGIN và quản lý danh tính session

### 9.1. Payload `LOGIN`

| Trường | Kích thước |
|---|---:|
| `username_length` | 2 byte |
| `username` | `username_length` byte UTF-8 |

Username hợp lệ PHẢI:

- Có độ dài 1–32 byte UTF-8.
- Chỉ gồm ASCII `A-Z`, `a-z`, `0-9`, `_` và `-`.
- Bắt đầu bằng chữ hoặc số.
- Không chứa `.`, `/`, `\`, khoảng trắng, control character hoặc byte `0x00`.
- Không trùng username của một session đang active.

Username được so sánh byte-for-byte và phân biệt hoa thường. `Alice` và `alice`
là hai namespace khác nhau.

### 9.2. LOGIN thành công

Server atomically:

1. Validate username.
2. Kiểm tra registry username active.
3. Cấp một `USER_ID` chưa dùng trong `1..65535`.
4. Đăng ký `(user_id, username, session)`.
5. Tạo hoặc mở namespace `storage/<username>/`.
6. Gửi `ACK(LOGIN)`.
7. Chuyển session sang `IDLE`.

`ACK(LOGIN)` dùng payload ACK bình thường:

```text
acked_opcode = LOGIN
next_offset  = 0
header.USER_ID = assigned_user_id
```

Client PHẢI lưu `header.USER_ID` và dùng ID đó cho mọi frame tiếp theo.

### 9.3. LOGIN thất bại

- Username sai: `INVALID_USERNAME`, giữ state `AUTHENTICATING`; Client có thể thử
  lại tối đa theo policy CLI.
- Username đang active: `USERNAME_IN_USE`, giữ state `AUTHENTICATING`.
- Server đủ client: `SERVER_BUSY`, Server đóng session sau khi gửi lỗi.
- Không tạo được namespace: `FILE_IO_ERROR` hoặc `ACCESS_DENIED`, đóng session.

Registry username và user ID PHẢI có lock. Entry PHẢI được giải phóng trong
`finally` khi session kết thúc sạch, timeout, framing error hoặc socket error.

### 9.4. Ví dụ LOGIN

Client LOGIN username `alice`:

```text
00 00 00 0B  00 01  00 00  00 05  61 6C 69 63 65
```

Server cấp `USER_ID = 7`:

```text
00 00 00 0E  00 20  00 07  00 01  00 00 00 00 00 00 00 00
```

## 10. Namespace và quy tắc đường dẫn

Namespace vật lý:

```text
server.storage_directory/
└── <username>/
    ├── public-file.bin
    ├── public-file.bin.part
    └── public-file.bin.part.meta
```

Server PHẢI:

- Lấy username từ authenticated session, không lấy từ payload file.
- Resolve mọi đường dẫn bên trong đúng namespace hiện tại.
- Không cho symlink, junction hoặc path traversal thoát namespace.
- Chỉ LIST và Download regular file đã publish.
- Không hiển thị `.part`, `.part.meta`, log hoặc file nội bộ.
- Không ghi đè file đã publish.
- Tạo `.part` và metadata theo chế độ exclusive khi bắt đầu transfer mới.

Tên file giữ quy tắc GĐ1: basename 1–255 byte UTF-8; không nhận `.`, `..`, `/`,
`\`, NUL, absolute path hoặc tên nội bộ.

Các session khác username có thể dùng cùng filename mà không xung đột. Nhiều
session cùng username bị ngăn từ LOGIN, nên chỉ một session được thao tác một
namespace tại một thời điểm. Server vẫn NÊN có lock theo `(username, filename)`
để bảo vệ publish, cleanup và khả năng mở rộng sau này.

## 11. Payload file và ACK

### 11.1. `FILE_LIST` và `FILE_LIST_RESP`

`FILE_LIST` có payload rỗng. `FILE_LIST_RESP` giữ schema v1:

```text
file_count: uint32
repeat file_count times:
    filename_length: uint16
    filename: utf8[filename_length]
    file_size: uint64
```

Danh sách sắp xếp tăng dần theo filename. Nếu response vượt payload tối đa,
Server trả `LIST_TOO_LARGE`.

### 11.2. `FILE_UPLOAD`

```text
filename_length: uint16
filename: utf8[filename_length]
total_size: uint64
start_offset: uint64
```

`start_offset` là resume hint do Client lưu từ transfer trước. Giá trị này PHẢI
không vượt `total_size`, nhưng offset Server trả trong ACK mới là giá trị có thẩm
quyền. Client lần đầu gửi `0`; khi reconnect CÓ THỂ gửi offset cuối đã biết.

### 11.3. `FILE_DOWNLOAD`

```text
filename_length: uint16
filename: utf8[filename_length]
requested_offset: uint64
```

`requested_offset` là kích thước file `.part` phía Client. Client PHẢI kiểm tra
regular file, không symlink và không vượt giới hạn `uint64`.

### 11.4. `FILE_INFO`

```text
filename_length: uint16
filename: utf8[filename_length]
total_size: uint64
start_offset: uint64
```

`start_offset` PHẢI bằng offset Server chấp nhận cho Download. Client chỉ ACK
`FILE_INFO` nếu file `.part` cục bộ có đúng kích thước này.

### 11.5. `FILE_CHUNK`

```text
offset: uint64
data: bytes[remaining_payload]
```

- Data có 1 byte đến `chunk_size_bytes`; file rỗng không gửi chunk.
- Chunk đầu bắt đầu tại offset đã thương lượng, không bắt buộc bằng `0`.
- Mỗi chunk kế tiếp PHẢI liên tục.
- Không chấp nhận overlap, gap, duplicate hoặc out-of-order chunk.
- Offset sai nhận `OFFSET_MISMATCH`.
- Bên nhận ghi ngay xuống `.part`, cập nhật digest và không load cả file vào RAM.

### 11.6. `FILE_CHECKSUM`

```text
final_size: uint64
sha256_digest: bytes[32]
```

Checksum luôn đại diện cho toàn bộ file từ byte `0` đến `final_size`, không chỉ
phần gửi sau resume. Hai phía PHẢI hash cả prefix cũ và phần mới bằng streaming.

### 11.7. `ACK`

```text
acked_opcode: uint16
next_offset: uint64
```

`next_offset` là byte đầu tiên chưa được xử lý. ACK cuối của checksum PHẢI có
`next_offset == total_size`.

### 11.8. `ERROR`

```text
failed_opcode: uint16
error_code: uint16
message_length: uint16
message: utf8[message_length]
```

Logic Client PHẢI dựa trên `error_code`, không parse nội dung `message`.

## 12. Resume Upload

### 12.1. Metadata file tạm

Mỗi Upload chưa hoàn tất dùng hai file nội bộ:

```text
<filename>.part
<filename>.part.meta
```

Metadata tối thiểu gồm:

- Protocol metadata version.
- Username.
- Remote filename.
- Declared `total_size`.
- Số byte đã persist.
- Thời điểm cập nhật cuối.

Metadata PHẢI được ghi atomically. Offset Server quảng bá không được lớn hơn số
byte thực sự đã flush/persist. `.part` và `.part.meta` không xuất hiện trong LIST.

### 12.2. Mở hoặc resume

Khi nhận `FILE_UPLOAD`, Server xử lý atomically:

1. Validate session, filename và `total_size`.
2. Nếu file chính đã tồn tại, trả `FILE_EXISTS`.
3. Nếu chưa có `.part`, tạo `.part` và `.part.meta`, offset bằng `0`.
4. Nếu đã có `.part`, validate metadata cùng username, filename và total size.
5. Nếu metadata khác total size và Client gửi `start_offset = 0`, xóa partial cũ
   theo cặp rồi bắt đầu transfer mới tại `0`.
6. Nếu metadata khác total size và Client gửi `start_offset != 0`, trả
   `RESUME_METADATA_MISMATCH` và giữ partial để tránh mất dữ liệu ngoài ý muốn.
7. Lấy kích thước `.part` đã persist làm `server_offset`.
8. Nếu `server_offset > total_size`, cleanup cặp partial/metadata và trả
   `RESUME_METADATA_MISMATCH`.
9. Server hash prefix `[0, server_offset)` bằng streaming để tiếp tục SHA-256.
10. Gửi `ACK(FILE_UPLOAD, server_offset)`.
11. Chuyển sang `RECEIVING_UPLOAD`.

Client PHẢI seek source đến đúng offset nhận trong ACK, khởi tạo SHA-256 bằng
cách hash prefix `[0, server_offset)`, rồi gửi phần còn lại.

### 12.3. Hoàn tất

Server kiểm tra:

- Byte thực nhận bằng `total_size`.
- `FILE_CHECKSUM.final_size` bằng `total_size`.
- SHA-256 toàn file khớp.

Nếu hợp lệ, Server flush/fsync, publish nguyên tử không ghi đè, xóa metadata và
trả `ACK(FILE_CHECKSUM, total_size)`. Upload chỉ thành công sau ACK cuối.

### 12.4. Chính sách giữ hoặc xóa partial

Giữ `.part` và metadata khi:

- TCP mất kết nối hoặc timeout giữa transfer.
- Server shutdown có kiểm soát sau khi đã persist offset.
- Client process bị dừng mà không gửi checksum.

Xóa `.part` và metadata khi:

- Checksum sai.
- Final size sai.
- Metadata hỏng hoặc trỏ ra ngoài namespace.
- Client yêu cầu transfer mới sau khi partial hết TTL theo policy Server.
- Publish thành công.

Offset mismatch trong một session làm kết thúc transfer hiện tại nhưng NÊN giữ
partial đến offset đã persist để Client reconnect và thương lượng lại.

### 12.5. Sequence

```text
Client                                      Server
   |-- FILE_UPLOAD(name,total,hint) ---------->|
   |<-- ACK(FILE_UPLOAD,server_offset) ---------|
   |-- FILE_CHUNK(offset=server_offset) -------->|
   |-- FILE_CHUNK(...) ------------------------>|
   |-- FILE_CHECKSUM(total,sha256) ------------>|
   |<-- ACK(FILE_CHECKSUM,total) / ERROR -------|
```

## 13. Resume Download

Client lưu Download chưa hoàn tất ở `<filename>.part`.

1. Client lấy kích thước `.part` làm `requested_offset`; không có file thì dùng
   `0`.
2. Client gửi `FILE_DOWNLOAD(filename, requested_offset)`.
3. Server validate regular file và `requested_offset <= total_size`.
4. Server trả `FILE_INFO(filename,total_size,requested_offset)`.
5. Client xác nhận `.part` đúng offset và gửi `ACK(FILE_INFO,requested_offset)`.
6. Hai bên hash prefix `[0, requested_offset)` bằng streaming.
7. Server gửi chunk bắt đầu đúng requested offset, rồi checksum toàn file.
8. Client validate size/checksum, publish file cục bộ và trả ACK cuối.

Nếu remote file không còn hoặc offset vượt size, Server trả `FILE_NOT_FOUND` hoặc
`OFFSET_MISMATCH`. Nếu checksum cuối sai, Client xóa `.part` để lần sau tải lại từ
đầu. Client giữ `.part` khi socket mất giữa Download.

```text
Client                                      Server
   |-- FILE_DOWNLOAD(name,local_offset) ------->|
   |<-- FILE_INFO(name,total,local_offset) ------|
   |-- ACK(FILE_INFO,local_offset) ------------>|
   |<-- FILE_CHUNK(offset=local_offset) ---------|
   |<-- FILE_CHUNK(...) -------------------------|
   |<-- FILE_CHECKSUM(total,sha256) -------------|
   |-- ACK(FILE_CHECKSUM,total) / ERROR -------->|
```

Server chỉ log Download thành công sau ACK checksum cuối.

## 14. Progress tracking

Progress là trách nhiệm hiển thị của Client, không thêm opcode riêng.

```text
percent = floor(processed_bytes * 100 / total_size)
```

Quy tắc:

- File 0 byte hiển thị 100% sau khi bắt đầu thành công.
- Upload resume bắt đầu tại `server_offset / total_size`.
- Download resume bắt đầu tại `requested_offset / total_size`.
- Upload dùng số byte đã giao thành công cho `send_all`; Download dùng số byte đã
  ghi thành công xuống `.part`.
- UI NÊN cập nhật khi tăng ít nhất 1% hoặc sau tối đa 250 ms, tránh print mỗi byte.
- Không hiển thị 100% thành công trước ACK checksum cuối.
- Workflow trả structured result; CLI chỉ hiển thị progress và kết quả.

## 15. Concurrency và giới hạn client

Server dùng bounded thread-per-client:

- Một accept loop duy nhất sở hữu listener.
- Mỗi accepted connection hợp lệ được giao cho một worker.
- Mỗi worker sở hữu đúng một socket và một `ServerSession`.
- `max_clients` là số session slot đồng thời, mặc định `10`.
- Slot được reserve/release atomically và luôn release trong `finally`.
- Không chia sẻ file object, digest hoặc state machine giữa session.
- Logger, active-user registry, ID allocator và filename lock registry phải
  thread-safe.

Khi hết slot, accept loop PHẢI không block vô hạn chờ worker. Server thực hiện
preface với timeout ngắn, echo preface, gửi:

```text
ERROR(
    failed_opcode = LOGIN,
    error_code = SERVER_BUSY,
    header.USER_ID = 0
)
```

sau đó đóng socket. Client CÓ THỂ retry với exponential backoff; không retry vòng
lặp chặt.

Server phải chứng minh bằng automated test:

- Ít nhất 10 client hoạt động đồng thời.
- Client thứ `max_clients + 1` bị từ chối đúng mã lỗi.
- Connect/disconnect lặp lại không rò thread, socket hoặc active-user entry.
- Upload/Download ở namespace khác nhau không làm hỏng dữ liệu.

## 16. Throttling theo client

Server áp giới hạn `bandwidth_limit_kib_per_second` riêng cho từng session. `0`
nghĩa là không giới hạn.

- Chỉ tính file data, không tính header/control frame.
- Upload được điều tiết bằng nhịp đọc; TCP backpressure làm Client chậm lại.
- Download được điều tiết trước hoặc giữa các lần gửi chunk.
- Dùng monotonic clock, không dùng wall clock.
- NÊN dùng token bucket với burst tối đa một chunk.
- Không giữ global lock trong lúc sleep/chờ token.
- Hai client mỗi người có limit riêng; không chia đôi một global limit.
- Thay đổi config chỉ áp dụng cho session mới, trừ khi implementation ghi rõ khác.

Test throttling dùng file đủ lớn để transfer kéo dài ít nhất 5 giây. Tốc độ trung
bình tính bằng `file_data_bytes / transfer_seconds` không được vượt ngưỡng cấu
hình quá 10%.

## 17. Máy trạng thái session

```text
CONNECTED
    |
    | preface v2 hợp lệ
    v
AUTHENTICATING
    |
    | LOGIN + ACK
    v
IDLE -------------------------------> CLOSING -> CLOSED
 |  \
 |   \-- FILE_DOWNLOAD -----------> SENDING_DOWNLOAD --\
 |                                                        > IDLE
 \------ FILE_UPLOAD -------------> RECEIVING_UPLOAD ----/
```

| State | Message Client được phép gửi |
|---|---|
| `CONNECTED` | Chỉ preface raw 8 byte |
| `AUTHENTICATING` | `LOGIN` với `USER_ID=0` |
| `IDLE` | LIST, Upload, Download, Disconnect |
| `RECEIVING_UPLOAD` | Chunk, checksum hoặc socket close |
| `SENDING_DOWNLOAD` | ACK/ERROR theo đúng bước Download hoặc socket close |
| `CLOSING`, `CLOSED` | Không message mới |

Message có framing đúng nhưng sai state nhận `INVALID_STATE`. Lỗi nghiệp vụ có
thể phục hồi đưa authenticated session về `IDLE`; framing/socket/authentication
fatal đóng session.

## 18. Mã lỗi

Các mã v1 được giữ nguyên:

| Hex | Tên | Phục hồi | Ý nghĩa |
|---:|---|---|---|
| `0x0001` | `INVALID_FRAME` | Fatal nếu mất đồng bộ | Header/length sai |
| `0x0002` | `UNSUPPORTED_OPCODE` | Có | Opcode chưa hỗ trợ |
| `0x0003` | `INVALID_PAYLOAD` | Tùy state | Payload sai schema |
| `0x0004` | `INVALID_STATE` | Tùy state | Message sai state |
| `0x0005` | `PAYLOAD_TOO_LARGE` | Fatal | Payload vượt giới hạn |
| `0x0006` | `INVALID_USER_ID` | Fatal sau LOGIN | User ID sai session |
| `0x0010` | `FILE_NOT_FOUND` | Có | File không tồn tại |
| `0x0011` | `FILE_EXISTS` | Có | File publish đã tồn tại |
| `0x0012` | `INVALID_FILENAME` | Có | Filename sai |
| `0x0013` | `ACCESS_DENIED` | Có/đóng transfer | Không có quyền I/O |
| `0x0014` | `FILE_IO_ERROR` | Có/đóng transfer | Lỗi I/O |
| `0x0015` | `SIZE_MISMATCH` | Có | Size sai |
| `0x0016` | `CHECKSUM_MISMATCH` | Có | SHA-256 sai |
| `0x0017` | `OFFSET_MISMATCH` | Có qua reconnect | Offset sai |
| `0x0018` | `TRANSFER_IN_PROGRESS` | Có | Session đang transfer |
| `0x0019` | `LIST_TOO_LARGE` | Có | LIST vượt payload |
| `0x00FF` | `INTERNAL_ERROR` | Tùy lỗi | Lỗi không phân loại |

Mã mới của v2:

| Hex | Tên | Phục hồi | Ý nghĩa |
|---:|---|---|---|
| `0x0007` | `AUTHENTICATION_REQUIRED` | Có trong auth state | Command trước LOGIN |
| `0x0008` | `INVALID_USERNAME` | Có | Username sai quy tắc |
| `0x0009` | `USERNAME_IN_USE` | Có | Username đang active |
| `0x000A` | `SERVER_BUSY` | Reconnect sau | Hết client slot |
| `0x001A` | `RESUME_METADATA_MISMATCH` | Có sau restart | Metadata partial không khớp |

Không được đổi giá trị error code sau protocol freeze.

## 19. Chính sách lỗi và đóng session

Lỗi nghiệp vụ có thể phục hồi:

- Invalid username hoặc username active khi đang authenticate.
- File không tồn tại, file đã tồn tại, filename sai.
- Resume không có hoặc metadata không khớp.
- Checksum/size mismatch sau khi đã cleanup transfer.

Lỗi phải đóng session:

- Preface sai.
- `LENGTH < 4`, payload quá lớn hoặc frame bị cắt giữa chừng.
- Payload không decode được mà stream/state không còn đáng tin.
- `USER_ID` thay đổi sau LOGIN.
- Socket error/timeout làm mất đồng bộ transfer.
- Server không thể bảo đảm namespace hoặc registry invariant.

Sau lỗi transfer có thể phục hồi, Server gửi ERROR rồi trở về `IDLE`. Sau lỗi
fatal, Server cố log nhưng không được tiếp tục parse cùng stream.

## 20. Logging bắt buộc

Mỗi log record session/command/transfer NÊN là JSON Lines và tối thiểu có:

- Timestamp UTC.
- IP và port Client.
- `user_id` và username nếu đã LOGIN.
- Opcode/command.
- Filename nếu có.
- Byte xử lý trong lần này và tổng file size.
- Resume offset.
- Duration và tốc độ KiB/s.
- Configured bandwidth limit.
- Success/failure, error code và checksum result.

Logger PHẢI thread-safe, mỗi event là một dòng hoàn chỉnh và không ghi raw file
data, secret hoặc stack trace ra response Client.

## 21. Config liên quan protocol

Các key đề xuất:

```ini
[server]
max_clients = 10
storage_directory = runtime/server-storage
partial_ttl_seconds = 86400

[network]
chunk_size_bytes = 32768
max_payload_bytes = 1048576
bandwidth_limit_kib_per_second = 500

[auth]
max_username_bytes = 32
```

Config parser PHẢI fail-fast với key lạ, số âm, `max_clients < 1`, chunk ngoài
4–64 KiB hoặc payload không chứa được chunk. Môi trường demo/chấm PHẢI cấu hình
`max_clients >= 10`.

## 22. Ví dụ frame v2

### 22.1. LIST của user 7

```text
00 00 00 04  00 10  00 07
```

### 22.2. Upload `data.bin`, 10.000.000 byte

```text
LENGTH      = 30 = 0x0000001E
OPCODE      = 0x0012
USER_ID     = 0x0007
name_length = 8
total_size  = 0x0000000000989680
start_offset = 0
```

```text
00 00 00 1E  00 12  00 07
00 08  64 61 74 61 2E 62 69 6E
00 00 00 00 00 98 96 80
00 00 00 00 00 00 00 00
```

### 22.3. ACK resume tại offset 6.000.000

```text
LENGTH      = 14 = 0x0000000E
OPCODE      = 0x0020
USER_ID     = 0x0007
acked       = 0x0012
next_offset = 0x00000000005B8D80
```

```text
00 00 00 0E  00 20  00 07
00 12  00 00 00 00 00 5B 8D 80
```

## 23. Test tương thích bắt buộc

### Framing và codec

- Preface v2 đúng; v1/sai magic/sai reserved bị từ chối.
- Header/payload bị chia qua nhiều lần receive.
- Nhiều frame gộp trong một receive.
- Length nhỏ hơn 4, overflow hoặc payload quá giới hạn.
- Encode/decode LOGIN, nonzero user ID và mọi error code mới.
- Hex fixture trong mục 22 decode đúng.

### Login và namespace

- Username boundary 1/32 byte; invalid UTF-8 và ký tự cấm.
- Hai client LOGIN cùng username: đúng một thành công.
- Username được giải phóng sau mọi đường đóng session.
- Hai username cùng filename nhìn thấy nội dung riêng.
- Path traversal, symlink và junction không thoát storage root.

### Concurrency và resilience

- Tối thiểu 10 client LIST/Upload/Download đồng thời.
- Client thứ 11 bị `SERVER_BUSY` khi max là 10.
- Connect/disconnect lặp ít nhất 100 vòng không leak tài nguyên.
- Logger không có JSON line bị xen kẽ.
- Một session framing lỗi không làm listener hoặc session khác dừng.

### Resume

- Upload và Download resume tại nhiều offset, gồm offset không chia hết chunk.
- Ngắt TCP ở 30–70%, reconnect, resume và checksum khớp.
- Server offset khác client hint; Client tuân theo offset Server.
- Partial/metadata hỏng, restart bằng `start_offset=0`, size mismatch, checksum
  mismatch và TTL cleanup.
- File rỗng, dưới 1 KiB, khoảng 10 MiB, trên 100 MiB và binary chứa NUL.

### Progress và throttling

- Progress không giảm, bắt đầu đúng resume offset và chỉ thành công 100% sau ACK.
- Limit riêng của hai client không ảnh hưởng lẫn nhau.
- Tốc độ trung bình không vượt limit quá 10% trên transfer đủ dài.
- Throttle không giữ global lock hoặc làm client khác starvation.

## 24. Ánh xạ yêu cầu Giai đoạn 2

| Rubric | Phần Mini-RFC liên quan | Bằng chứng chính |
|---|---|---|
| R2.1 Concurrency | 15, 17, 19, 23 | 10 client, capacity và leak test |
| R2.2 Protocol | 3–9, 11, 18, 22 | Codec, payload và hex fixture |
| R2.3 Namespace | 9–10, 15 | Isolation và parallel transfer test |
| R2.4 Resume | 11–13 | Disconnect/reconnect và checksum |
| R2.5 Progress | 14 | Callback/UI progress test |
| R2.6 Throttling | 16 | Đo tốc độ với sai số tối đa 10% |
| R2.7 Edge cases | 10, 15, 18–19 | File conflict và `SERVER_BUSY` |

## 25. Tiêu chí protocol freeze

Mini-RFC được freeze khi cả ba thành viên xác nhận:

- Opcode/error code không trùng và có giá trị cố định.
- Mọi payload có schema, byte order, giới hạn và validation.
- LOGIN/USER_ID và namespace không còn quyết định mở.
- Resume Upload/Download có sequence và cleanup policy rõ ràng.
- Concurrency, server-full và throttling có hành vi quan sát được.
- Hex fixtures có automated test.
- Test plan ánh xạ đủ R2.1–R2.7 của đề bài.

Sau freeze:

- Không đổi ý nghĩa `LENGTH`, byte order hoặc checksum.
- Không chèn trường vào giữa payload đã freeze.
- Thay đổi wire không tương thích phải tăng `VERSION`.
- Thay đổi chỉ về CLI/UI không bắt buộc tăng protocol version.

## 26. Phân công triển khai theo contract

- TV1 sở hữu preface v2, LOGIN, USER_ID, state auth, namespace và integration.
- TV2 sở hữu bounded concurrency, client capacity, registry synchronization và
  throttling.
- TV3 sở hữu resume Upload/Download và progress tracking.
- Mọi thành viên dùng codec chung; không tự encode/decode frame trong handler.
- PR feature phải có base `feat/phase2-integration` và không tự thay đổi Mini-RFC
  nếu chưa có review của cả nhóm.
