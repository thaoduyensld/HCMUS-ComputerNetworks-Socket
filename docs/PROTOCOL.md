# HCMUS Socket File Transfer Protocol

## 1. Trạng thái tài liệu

| Thuộc tính | Giá trị |
|---|---|
| Tên giao thức | HCMUS Socket File Transfer Protocol |
| Phiên bản | 1 |
| Giai đoạn áp dụng | Giai đoạn 1 |
| Transport | TCP |
| Byte order | Network byte order (big-endian) |
| Mã hóa text | UTF-8 |
| Checksum | SHA-256 |
| Chunk mặc định | 32 KiB (32.768 byte) |
| Mô hình xử lý | Một client tại một thời điểm |

Tài liệu này là hợp đồng byte-level giữa Client và Server. Mọi thay đổi ảnh
hưởng đến preface, header, opcode, payload hoặc trình tự message phải:

1. Cập nhật tài liệu này.
2. Được cả ba thành viên đồng ý.
3. Cập nhật Client, Server và test trong cùng một đợt tích hợp.
4. Tăng protocol version nếu thay đổi không tương thích.

## 2. Mục tiêu

Protocol v1 hỗ trợ đúng ba thao tác người dùng:

- `LIST`: lấy danh sách file trên server.
- `UPLOAD <filename>`: tải file từ client lên server.
- `DOWNLOAD <filename>`: tải file từ server về client.

Giao thức phải:

- Giải quyết message boundary trên TCP.
- Hoạt động khi một frame bị chia thành nhiều lần nhận.
- Hoạt động khi nhiều frame được gộp trong một lần nhận.
- Truyền file theo chunk, không đọc toàn bộ file vào RAM.
- Phát hiện dữ liệu không toàn vẹn bằng SHA-256.
- Xử lý client ngắt kết nối mà không làm server crash.
- Có đường mở rộng cho login, user ID và resume ở giai đoạn 2.

## 3. Ngoài phạm vi giai đoạn 1

Phiên bản này chưa hỗ trợ:

- Nhiều client đồng thời.
- Đăng nhập hoặc mật khẩu.
- Resume transfer.
- Xóa file.
- Giới hạn băng thông.
- Nén hoặc mã hóa dữ liệu.
- Nhiều transfer đồng thời trên cùng kết nối.

`USER_ID` vẫn có trong header nhưng luôn bằng `0` ở giai đoạn 1.

## 4. Nguyên tắc nhận dữ liệu TCP

TCP là byte stream và không giữ ranh giới giữa các lần gửi. Bên nhận không được
giả định một lần gọi hàm nhận sẽ trả về đủ header, đủ payload hoặc đúng một
frame.

Quy trình nhận frame:

1. Nhận chính xác 4 byte `LENGTH`.
2. Chuyển `LENGTH` từ network byte order sang host byte order.
3. Kiểm tra `LENGTH` trước khi cấp phát bộ nhớ.
4. Nhận chính xác thêm `LENGTH` byte.
5. Đọc `OPCODE`, `USER_ID` và payload.
6. Kiểm tra payload theo opcode.
7. Chỉ xử lý message sau khi nhận đủ frame.

TCP đóng trước khi nhận đủ preface, header hoặc payload được xem là kết nối bị
gián đoạn.

## 5. Connection preface

Ngay sau khi TCP kết nối thành công, Client và Server xác nhận protocol bằng
preface cố định 8 byte.

| Trường | Kích thước | Giá trị |
|---|---:|---|
| `MAGIC` | 4 byte | `0x48434D55`, tương ứng `"HCMU"` |
| `VERSION` | 2 byte | `1` |
| `RESERVED` | 2 byte | `0` |

Tất cả trường sử dụng network byte order.

Trình tự:

1. Client gửi preface.
2. Server nhận chính xác 8 byte.
3. Server kiểm tra `MAGIC`, `VERSION` và `RESERVED`.
4. Nếu hợp lệ, Server gửi lại cùng preface.
5. Client kiểm tra preface phản hồi và chuyển phiên sang `IDLE`.
6. Nếu không hợp lệ, Server ghi log và đóng kết nối.

Không gửi frame nghiệp vụ trước khi preface hoàn thành.

## 6. Cấu trúc frame

```text
+----------------+----------------+----------------+------------------+
| LENGTH         | OPCODE         | USER_ID        | PAYLOAD          |
| 4 byte         | 2 byte         | 2 byte         | biến đổi         |
+----------------+----------------+----------------+------------------+
```

### 6.1. `LENGTH`

- Số nguyên không dấu 32 bit, network byte order.
- Là tổng số byte phía sau trường `LENGTH`.
- Bao gồm `OPCODE`, `USER_ID` và `PAYLOAD`.
- Không bao gồm chính 4 byte `LENGTH`.

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

Số nguyên không dấu 16 bit, network byte order. Opcode xác định loại message và
cách diễn giải payload.

### 6.3. `USER_ID`

Số nguyên không dấu 16 bit. Giá trị phải bằng `0` ở giai đoạn 1. Frame có
`USER_ID != 0` bị từ chối với lỗi `INVALID_USER_ID`.

### 6.4. `PAYLOAD`

- Dữ liệu nhị phân có kích thước biến đổi.
- Text được mã hóa UTF-8.
- Chuỗi không dùng byte `0x00` làm terminator.
- Mỗi chuỗi phải có trường độ dài đi kèm.
- Không dùng hàm xử lý chuỗi trên dữ liệu file.

## 7. Giới hạn

| Giới hạn | Giá trị |
|---|---:|
| Payload tối đa mặc định | 1 MiB |
| File chunk mặc định | 32 KiB |
| File chunk hợp lệ | 4 KiB đến 64 KiB |
| Tên file tối đa | 255 byte UTF-8 |
| SHA-256 digest | 32 byte |
| Transfer hoạt động trên một phiên | 1 |

`max_payload_bytes` phải đủ chứa offset 8 byte và dữ liệu chunk. File có thể lớn
hơn payload tối đa vì được chia thành nhiều `FILE_CHUNK`.

## 8. Opcode

| Opcode | Tên | Chiều | Ý nghĩa |
|---:|---|---|---|
| `0x0002` | `DISCONNECT` | Client → Server | Kết thúc phiên |
| `0x0010` | `FILE_LIST` | Client → Server | Yêu cầu danh sách file |
| `0x0011` | `FILE_LIST_RESP` | Server → Client | Phản hồi danh sách |
| `0x0012` | `FILE_UPLOAD` | Client → Server | Bắt đầu upload |
| `0x0013` | `FILE_DOWNLOAD` | Client → Server | Yêu cầu download |
| `0x0014` | `FILE_CHUNK` | Hai chiều | Dữ liệu một phần file |
| `0x0015` | `FILE_DELETE` | Dành cho GĐ2 | Không dùng ở GĐ1 |
| `0x0016` | `FILE_INFO` | Server → Client | Metadata file download |
| `0x0017` | `FILE_CHECKSUM` | Hai chiều | Kích thước và SHA-256 |
| `0x0020` | `ACK` | Hai chiều | Xác nhận message |
| `0x00FF` | `ERROR` | Hai chiều | Thông báo lỗi |

Opcode không được định nghĩa nhận lỗi `UNSUPPORTED_OPCODE`.

## 9. Kiểu dữ liệu

| Kiểu | Kích thước | Mô tả |
|---|---:|---|
| `uint16` | 2 byte | Số nguyên không dấu, big-endian |
| `uint32` | 4 byte | Số nguyên không dấu, big-endian |
| `uint64` | 8 byte | Số nguyên không dấu, big-endian |
| `utf8[n]` | `n` byte | Chuỗi UTF-8 không có terminator |
| `bytes[n]` | `n` byte | Dữ liệu nhị phân thô |

## 10. Quy tắc tên file

Tên file trên mạng là basename, không phải đường dẫn đầy đủ.

Tên file hợp lệ phải:

- Không rỗng và không dài quá 255 byte UTF-8.
- Không phải `.` hoặc `..`.
- Không chứa byte `0x00`, `/` hoặc `\`.
- Không phải đường dẫn tuyệt đối.
- Không chứa thành phần điều hướng thư mục.
- Không làm đường dẫn kết quả thoát khỏi storage root.
- Hợp lệ theo hệ điều hành của bên nhận.

Không được tự động loại bỏ phần nguy hiểm rồi tiếp tục; tên không hợp lệ phải bị
từ chối.

Chính sách giai đoạn 1:

- Upload không ghi đè file đã tồn tại.
- Download không ghi đè file cục bộ đã tồn tại.
- File trùng tên nhận lỗi `FILE_EXISTS`.

## 11. Payload

### 11.1. `DISCONNECT`

Payload rỗng. Server trả `ACK`, đóng client socket và quay lại chờ client tiếp
theo. TCP đóng trực tiếp vẫn phải được xử lý an toàn.

### 11.2. `FILE_LIST`

Payload rỗng. Chỉ hợp lệ khi phiên ở trạng thái `IDLE`.

### 11.3. `FILE_LIST_RESP`

| Trường | Kích thước |
|---|---:|
| `file_count` | 4 byte |
| `entries` | Biến đổi |

Mỗi entry:

| Trường | Kích thước |
|---|---:|
| `filename_length` | 2 byte |
| `filename` | `filename_length` byte |
| `file_size` | 8 byte |

Danh sách được sắp xếp tăng dần theo tên. File `.part`, log và file nội bộ không
được xuất hiện. Nếu danh sách vượt payload tối đa, Server trả
`LIST_TOO_LARGE`.

### 11.4. `FILE_UPLOAD`

| Trường | Kích thước |
|---|---:|
| `filename_length` | 2 byte |
| `filename` | `filename_length` byte |
| `total_size` | 8 byte |
| `start_offset` | 8 byte |

Trong giai đoạn 1, `start_offset` phải bằng `0`. `total_size` có thể bằng `0`.

Server:

1. Kiểm tra tên file, file trùng và khả năng ghi.
2. Tạo file tạm có hậu tố `.part`.
3. Trả `ACK` với `next_offset = 0`, hoặc trả `ERROR`.

### 11.5. `FILE_DOWNLOAD`

| Trường | Kích thước |
|---|---:|
| `filename_length` | 2 byte |
| `filename` | `filename_length` byte |
| `requested_offset` | 8 byte |

`requested_offset` phải bằng `0` ở giai đoạn 1. Nếu file hợp lệ, Server trả
`FILE_INFO`; nếu không, Server trả `ERROR`.

### 11.6. `FILE_INFO`

| Trường | Kích thước |
|---|---:|
| `filename_length` | 2 byte |
| `filename` | `filename_length` byte |
| `total_size` | 8 byte |
| `start_offset` | 8 byte |

Client kiểm tra metadata, tạo file `.part` và trả `ACK` cho `FILE_INFO`. Server
chỉ gửi chunk sau ACK này.

### 11.7. `FILE_CHUNK`

| Trường | Kích thước |
|---|---:|
| `offset` | 8 byte |
| `data` | Phần payload còn lại |

```text
DATA_SIZE = PAYLOAD_SIZE - 8
```

Quy tắc:

- `data` là byte thô.
- Mỗi chunk có ít nhất một byte và không vượt chunk size.
- Chunk cuối có thể nhỏ hơn chunk size.
- File 0 byte không gửi `FILE_CHUNK`.
- Offset đầu tiên bằng `0`.
- Offset tiếp theo bằng offset trước cộng số byte dữ liệu trước.
- Giai đoạn 1 không chấp nhận chunk lệch thứ tự hoặc trùng offset.
- Offset sai nhận lỗi `OFFSET_MISMATCH`.

Bên nhận ghi chunk xuống file ngay và đồng thời cập nhật SHA-256.

### 11.8. `FILE_CHECKSUM`

Payload cố định 40 byte:

| Trường | Kích thước |
|---|---:|
| `final_size` | 8 byte |
| `sha256_digest` | 32 byte |

Digest là 32 byte nhị phân thô, không phải chuỗi hex.

Bên nhận kiểm tra:

1. `final_size` bằng kích thước khai báo.
2. Tổng byte thực nhận bằng `final_size`.
3. SHA-256 tự tính bằng digest nhận được.

Nếu khớp, đóng file, đổi `.part` thành file chính thức và trả `ACK`. Nếu không
khớp, xóa `.part` và trả `SIZE_MISMATCH` hoặc `CHECKSUM_MISMATCH`.

### 11.9. `ACK`

Payload cố định 10 byte:

| Trường | Kích thước |
|---|---:|
| `acked_opcode` | 2 byte |
| `next_offset` | 8 byte |

`next_offset` là số byte đã xử lý thành công. ACK cuối của
`FILE_CHECKSUM` phải có `next_offset == total_size`.

### 11.10. `ERROR`

| Trường | Kích thước |
|---|---:|
| `failed_opcode` | 2 byte |
| `error_code` | 2 byte |
| `message_length` | 2 byte |
| `message` | `message_length` byte |

`message` là UTF-8 để hiển thị và ghi log. Logic chương trình phải dựa trên
`error_code`, không dựa trên nội dung message.

## 12. Mã lỗi

| Mã | Tên | Ý nghĩa |
|---:|---|---|
| `0x0001` | `INVALID_FRAME` | Header hoặc length không hợp lệ |
| `0x0002` | `UNSUPPORTED_OPCODE` | Opcode chưa hỗ trợ |
| `0x0003` | `INVALID_PAYLOAD` | Payload sai cấu trúc |
| `0x0004` | `INVALID_STATE` | Message sai trạng thái |
| `0x0005` | `PAYLOAD_TOO_LARGE` | Payload vượt giới hạn |
| `0x0006` | `INVALID_USER_ID` | User ID khác 0 |
| `0x0010` | `FILE_NOT_FOUND` | File không tồn tại |
| `0x0011` | `FILE_EXISTS` | File đích đã tồn tại |
| `0x0012` | `INVALID_FILENAME` | Tên file không hợp lệ |
| `0x0013` | `ACCESS_DENIED` | Không có quyền đọc hoặc ghi |
| `0x0014` | `FILE_IO_ERROR` | Lỗi đọc hoặc ghi file |
| `0x0015` | `SIZE_MISMATCH` | Kích thước không khớp |
| `0x0016` | `CHECKSUM_MISMATCH` | SHA-256 không khớp |
| `0x0017` | `OFFSET_MISMATCH` | Offset chunk không đúng |
| `0x0018` | `TRANSFER_IN_PROGRESS` | Đang có transfer khác |
| `0x0019` | `LIST_TOO_LARGE` | Danh sách vượt payload |
| `0x0020` | `SERVER_BUSY` | Server đã đạt giới hạn client đồng thời (Phase 2) |
| `0x00FF` | `INTERNAL_ERROR` | Lỗi không phân loại được |

## 13. Trình tự `LIST`

```text
Client                               Server
   |---------- FILE_LIST -------------->|
   |<------- FILE_LIST_RESP ------------|
```

Nếu có lỗi, Server trả `ERROR`. Sau response hoặc lỗi có thể phục hồi, phiên
trở về `IDLE`.

## 14. Trình tự `UPLOAD`

```text
Client                               Server
   |--------- FILE_UPLOAD ------------->|
   |<------------- ACK -----------------|
   |---------- FILE_CHUNK ------------->|
   |---------- FILE_CHUNK ------------->|
   |              ...                   |
   |-------- FILE_CHECKSUM ------------>|
   |<--------- ACK hoặc ERROR -----------|
```

Upload chỉ thành công sau ACK cuối của `FILE_CHECKSUM`.

## 15. Trình tự `DOWNLOAD`

```text
Client                               Server
   |-------- FILE_DOWNLOAD ------------>|
   |<--------- FILE_INFO ---------------|
   |------------- ACK ----------------->|
   |<--------- FILE_CHUNK ---------------|
   |<--------- FILE_CHUNK ---------------|
   |              ...                   |
   |<------- FILE_CHECKSUM --------------|
   |-------- ACK hoặc ERROR ------------>|
```

Server chỉ ghi log download thành công sau khi nhận ACK cuối.

## 16. Máy trạng thái phiên

### `CONNECTED`

TCP đã kết nối nhưng preface chưa hoàn tất. Không cho phép message nghiệp vụ.

### `IDLE`

Client được phép gửi `FILE_LIST`, `FILE_UPLOAD`, `FILE_DOWNLOAD` hoặc
`DISCONNECT`.

### `RECEIVING_UPLOAD`

Server chỉ chấp nhận `FILE_CHUNK`, `FILE_CHECKSUM` hoặc kết nối đóng.

### `SENDING_DOWNLOAD`

Server chờ ACK của `FILE_INFO`, sau đó gửi chunk và checksum, rồi chờ ACK hoặc
ERROR cuối.

### `CLOSING`

Hai phía giải phóng tài nguyên và đóng socket.

Message không hợp lệ với trạng thái hiện tại nhận `INVALID_STATE`.

## 17. Ngắt kết nối và file tạm

Nếu kết nối đóng ở trạng thái `IDLE`, Server ghi log, giải phóng socket và quay
lại chờ client tiếp theo.

Nếu kết nối đóng giữa upload:

- Server đóng và xóa file `.part`.
- Ghi log thất bại và số byte đã nhận.
- Không để file xuất hiện trong `LIST`.
- Quay lại chờ client mới.

Nếu kết nối đóng giữa download:

- Server đóng file nguồn.
- Client đóng và xóa file `.part`.
- Hai phía ghi nhận transfer thất bại.

Resume không được thực hiện trong giai đoạn 1.

## 18. Khả năng phục hồi sau lỗi

Các lỗi nghiệp vụ như `FILE_NOT_FOUND`, `FILE_EXISTS` và `INVALID_FILENAME`
không bắt buộc đóng kết nối. Sau `ERROR`, phiên có thể trở về `IDLE`.

Các lỗi sau phải đóng kết nối vì ranh giới hoặc trạng thái không còn đáng tin:

- Preface sai.
- `LENGTH` không hợp lệ.
- Payload vượt giới hạn.
- Frame bị cắt giữa chừng.
- Payload không thể giải mã an toàn.
- Trạng thái transfer bị mất đồng bộ.

## 19. Checksum

- Thuật toán duy nhất là SHA-256.
- Hai phía tính checksum trong lúc streaming.
- Không đọc lại toàn bộ file vào RAM.
- Digest truyền dưới dạng 32 byte nhị phân.
- File chỉ được công nhận sau khi checksum khớp.
- SHA-256 ở đây kiểm tra toàn vẹn, không cung cấp xác thực hoặc mã hóa.

## 20. Logging liên quan protocol

Mỗi command hoặc transfer phải ghi:

- Thời điểm bắt đầu và kết thúc.
- IP client.
- Opcode hoặc tên lệnh.
- Tên file nếu có.
- Số byte đã xử lý.
- Thời gian xử lý.
- Tốc độ KB/s.
- Thành công hoặc thất bại.
- Error code nếu có.
- Kết quả checksum.

Không ghi raw file data vào log.

## 21. Ví dụ frame

### `FILE_LIST`

`FILE_LIST` không có payload:

```text
LENGTH   = 4
OPCODE   = 0x0010
USER_ID  = 0
```

Hex dump:

```text
00 00 00 04  00 10  00 00
```

### Danh sách rỗng

Payload chứa `file_count = 0`:

```text
00 00 00 08  00 11  00 00  00 00 00 00
```

### Upload `data.bin`

Với tên dài 8 byte, kích thước 10.000.000 byte và offset 0:

```text
PAYLOAD_SIZE = 2 + 8 + 8 + 8 = 26
LENGTH       = 2 + 2 + 26 = 30 = 0x0000001E
```

### Chunk 4 KiB

```text
PAYLOAD_SIZE = 8 + 4096 = 4104
LENGTH       = 2 + 2 + 4104 = 4108 = 0x0000100C
```

## 22. Test tương thích bắt buộc

- Preface đúng, sai magic và sai version.
- Header hoặc payload bị chia thành nhiều lần nhận.
- Hai frame đến trong một lần nhận.
- `LENGTH < 4` hoặc payload vượt giới hạn.
- Opcode không tồn tại hoặc user ID khác 0.
- Tên file rỗng, `..`, có `/` hoặc `\`.
- File 0 byte, dưới 1 KiB, khoảng 10 MiB và trên 100 MiB.
- File nhị phân có byte `0x00`.
- Offset không liên tục.
- Client ngắt giữa upload hoặc download.
- Checksum mismatch.
- Kết nối lại sau một phiên lỗi.

## 23. Mở rộng sang giai đoạn 2

Giai đoạn 2 có thể bổ sung login, namespace riêng, `FILE_DELETE`, resume, nhiều
client, throttling và progress tracking.

`USER_ID`, `start_offset`, `requested_offset` và offset trong mỗi chunk đã có từ
giai đoạn 1 để giảm thay đổi cấu trúc. Concurrency không được làm thay đổi cách
encode hoặc decode frame.

## 24. Protocol freeze

Sau khi cả nhóm duyệt tài liệu:

- Không đổi giá trị opcode.
- Không đổi kích thước trường.
- Không đổi ý nghĩa `LENGTH`.
- Không thêm trường vào giữa payload đã có.
- Không đổi byte order hoặc checksum algorithm.

Thay đổi không tương thích phải tăng `VERSION` và cập nhật Client, Server, test
cùng lúc.
