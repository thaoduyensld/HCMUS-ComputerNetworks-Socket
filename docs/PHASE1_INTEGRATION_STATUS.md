# Trạng thái và kế hoạch tích hợp Giai đoạn 1

> Cập nhật ngày 06/08/2026. Tài liệu này là nguồn mô tả công việc hiện tại
> của nhóm trong giai đoạn tích hợp. Đề bài gốc vẫn là tài liệu có thẩm quyền
> cao nhất.

## Trạng thái thực thi sau integration

TV1 đã áp dụng phần Download/logging và client Upload của TV3, viết lại server
Upload, đăng ký đủ ba handler, loại implementation Upload cũ và bổ sung test
TCP end-to-end. Trạng thái integration đã được xác minh:

- Python: `228 passed, 1 skipped`.
- Luồng TCP thật đã pass cho file rỗng và binary:
  `LIST -> UPLOAD -> LIST -> DOWNLOAD -> LIST -> DISCONNECT`.
- Upload trùng tên trả `FILE_EXISTS` và session vẫn tiếp tục hoạt động.
- Client ngắt giữa Upload làm `.part` được dọn.
- Logger ghi được LIST, Upload, Download, Disconnect và kết quả checksum.
- Benchmark 512 byte, 10 MiB và 120 MiB đã pass checksum.
- Peak Python allocation khi transfer 120 MiB khoảng 418 KiB.
- C++ Debug: build thành công, `2/2` ctest pass.
- C++ Release: build thành công, `2/2` ctest pass.
- Hai console entry point client/server hoạt động.

Việc còn lại sau commit/push là review PR integration và merge vào `main`.

## 1. Căn cứ yêu cầu

Tài liệu được đối chiếu với:

- Đề bài `Socket_Programming_HK3_2026.docx (1).pdf`, đặc biệt các trang 3,
  4 và 11.
- `docs/PROTOCOL.md`.
- `docs/architecture.md`.
- `docs/TEST_PLAN.md`.
- `docs/WORKFLOW.md`.
- Lịch sử Git và code trên các branch remote tại ngày cập nhật.

Các yêu cầu bắt buộc của Giai đoạn 1 theo đề bài:

1. Server TCP phục vụ tuần tự một client tại một thời điểm và tiếp tục nhận
   client mới sau khi phiên trước kết thúc hoặc gặp lỗi.
2. Client có đúng ba lệnh `LIST`, `UPLOAD <filename>` và
   `DOWNLOAD <filename>`.
3. File được truyền theo chunk, không đọc toàn bộ file vào RAM.
4. Message boundary trên TCP được xử lý bằng framing rõ ràng.
5. Client và server kiểm tra checksum sau transfer.
6. Server ghi log thời điểm, IP client, lệnh, thời gian xử lý và tốc độ trung
   bình.
7. File không tồn tại, filename không hợp lệ và client ngắt giữa transfer
   không làm server treo hoặc thoát.
8. Báo cáo phải giải thích framing và có benchmark ít nhất ba kích thước file.

## 2. Mốc Git trước khi integration

| Nhánh | Commit remote | Trạng thái |
|---|---|---|
| `main` | `d3e1376` | Đã merge PR #8 LIST/session |
| `feat/python-server-integration` | `d3e1376` | Nền tích hợp ban đầu, lúc đó giống `main` |
| `fix/upload-handler-refactor` | `f391054` | Branch TV2, chưa merge |
| `feat/python-server-logging` | `c4d8b8e` | Branch TV3, chưa merge |

Merge base của cả hai branch TV2 và TV3 với integration là `d3e1376`. Vì vậy
mọi PR trong đợt này phải có base là `feat/python-server-integration`, không
merge trực tiếp vào `main`.

## 3. Sự thật về trạng thái chạy hiện tại

### 3.1 `main` và integration tại `d3e1376`

Đã có:

- Protocol, framing, message codecs và config.
- `ClientSession` và `ServerSession`.
- Server listener tuần tự và khả năng nhận client mới sau phiên lỗi.
- State machine gồm `CONNECTED`, `IDLE`, `RECEIVING_UPLOAD`,
  `SENDING_DOWNLOAD`, `CLOSING`, `CLOSED`.
- Client và server `LIST`.
- Client và server workflow Download ở cấp module.
- Upload phiên bản cũ trong `client_upload.py` và `server_upload.py`.
- Console command client và server.
- `200 passed, 1 skipped` trên integration hiện tại.

Chưa có trong application thật:

- Upload dùng `ClientSession`/`ServerSession` thống nhất.
- `UPLOAD` trong client command registry.
- Upload handler trong server dispatcher hoạt động đúng.
- Download handler mặc định trong server dispatcher.
- Server logging theo yêu cầu đề bài.
- Luồng TCP thật `LIST -> UPLOAD -> LIST -> DOWNLOAD -> LIST`.
- Benchmark ba kích thước file và số liệu báo cáo.

Vì vậy `main` và integration hiện chưa đạt Giai đoạn 1 dù unit test đang pass.

### 3.2 Branch TV2: `fix/upload-handler-refactor`

Phạm vi thay đổi:

- Thêm `client/upload.py`.
- Thêm `server/upload.py`.
- Sửa `server/session.py` để đăng ký Upload.
- Thêm unit và end-to-end test Upload.
- Kết quả hiện tại: `206 passed, 1 skipped`.

Branch chưa sẵn sàng merge vì còn các lỗi không được test hiện tại phát hiện:

1. Dùng `session.config.server.storage_dir`, trong khi field đúng là
   `storage_directory`. Upload qua dispatcher thật sẽ lỗi `AttributeError`.
2. Dùng `ErrorCode.FILE_SIZE_MISMATCH`, trong khi enum đúng là
   `ErrorCode.SIZE_MISMATCH`.
3. Offset sai đang trả `INVALID_FRAME` thay vì `OFFSET_MISMATCH`.
4. `ProgressTracker.open()` dùng chế độ `wb`, có thể ghi đè file `.part`.
   Phải dùng exclusive creation hoặc cơ chế tương đương.
5. Server handler vẫn nhận request đã parse và `storage_dir`; interface chưa
   phải `(ServerSession, Frame)` như dispatcher thống nhất.
6. Client Upload chưa kiểm tra đầy đủ `ACK.next_offset`.
7. Client Upload chưa dùng đầy đủ `chunk_size_bytes` và
   `max_payload_bytes` từ session config.
8. Client Upload chỉ `print()`, chưa trả `UploadResult` có cấu trúc.
9. Test gọi `session.receive()` và handler thủ công, không chạy qua handshake,
   `serve()`, dispatcher và state machine thật.
10. Branch làm yếu invariant của handler built-in bằng cách cho phép override
    mọi handler, thay vì chỉ cho phép extension có kiểm soát.
11. Module Upload cũ và mới cùng tồn tại, tạo hai implementation cạnh tranh.

Kết luận: không merge branch TV2 nguyên trạng.

### 3.3 Branch TV3: `feat/python-server-logging`

Phạm vi Download/logging:

- Structured JSON Lines logger.
- Loại `server.log` khỏi LIST và Download.
- Adapter Download cho `ServerSession`.
- Đăng ký default Download handler.
- Log connection, disconnection và command lifecycle.
- Quản lý vòng đời logger trong server application.
- Test logger và Download integration.

Branch còn chứa ba commit Upload client ngoài phạm vi logging:

- `e6746f4`: session-based streaming Upload.
- `1d83271`: tích hợp Upload vào client CLI.
- `c4d8b8e`: test Upload workflow và CLI dispatch.

Kết quả branch đầy đủ: `218 passed, 1 skipped`.

Implementation client Upload của TV3 tốt hơn bản TV2 ở các điểm:

- Dùng `ClientSession`.
- Dùng chunk size và max payload từ config.
- Kiểm tra ACK opcode và offset.
- Trả `UploadResult`.
- Có progress callback và CLI adapter.

Tuy nhiên không merge branch TV3 nguyên trạng trước TV2 vì cả hai cùng thêm
`client/upload.py` và cùng sửa `server/session.py`. Phải tách phần
Download/logging trước.

### 3.4 Integration local sau khi TV1 hợp nhất

Implementation cuối hiện dùng:

- `client/upload.py` của TV3, được TV1 harden thêm cho regular file, source
  thay đổi kích thước và protocol desynchronization.
- `server/upload.py` mới do TV1 viết lại với exclusive `.part`, kiểm tra
  offset/size/SHA-256 và atomic no-overwrite publication.
- Download adapter và JSON Lines logger của TV3.
- Upload và Download đều trả kết quả có cấu trúc cho logger.
- `ServerSession` có default handler LIST, Upload, Download và Disconnect.
- `client/app.py` đăng ký LIST, Upload và Download.
- `test_phase1_end_to_end.py` chạy toàn chuỗi trên một TCP session.
- `scripts/benchmark_phase1.py` sinh file và benchmark qua loopback TCP.

Các module cũ `client_upload.py`, `server_upload.py`, `file_transfer.py` và
test Upload thủ công cũ đã được loại bỏ.

## 4. Quyết định tích hợp

Trình tự chính thức:

1. Tạo branch sạch cho Download/logging tại commit `03f7021`.
2. Review, sửa nếu cần và merge branch sạch vào
   `feat/python-server-integration`.
3. Tạo branch leader-owned để hợp nhất Upload trên nền integration mới.
4. Dùng client Upload của TV3 làm nền.
5. Dùng thuật toán server Upload của TV2 làm nguồn tham khảo, sửa toàn bộ lỗi
   trước khi tích hợp.
6. TV1 đăng ký đủ ba command/handler và thống nhất logging.
7. Chạy regression, file-size matrix, recovery test và benchmark.
8. Chỉ sau khi toàn bộ tiêu chí pass mới mở PR
   `feat/python-server-integration -> main`.

Không merge trực tiếp branch TV2 hoặc TV3 vào `main`.

## 5. Công việc TV1 phải làm

TV1 là leader, integration owner, reviewer và người sửa code cuối cùng của TV2
và TV3. TV1 chịu trách nhiệm về hành vi end-to-end, không chỉ registry.

### Pha A - Làm sạch và tích hợp TV3

#### A1. Tạo branch logging sạch

Tạo `feat/python-server-logging-clean` tại commit `03f7021`, cập nhật nó lên
integration mới nhất và xác nhận diff không chứa:

- `client/upload.py`.
- Thay đổi Upload trong `client/app.py`.
- `tests/test_client_upload.py`.

#### A2. Review logger

Xác nhận:

- Mỗi event là một JSON object trên một dòng.
- Có timestamp UTC, IP, port, command, filename, byte count, duration, speed,
  result và error code.
- Logger được tạo một lần ở server application và đóng khi Ctrl+C.
- Lỗi ghi log không làm server session crash.
- `server.log` không xuất hiện trong LIST và không thể Download.
- Không log nội dung file hoặc dữ liệu nhạy cảm.

#### A3. Review Download integration

Xác nhận:

- `FILE_DOWNLOAD` được đăng ký mặc định đúng một lần.
- Adapter nhận `(ServerSession, Frame)`, parse request rồi gọi thuật toán
  Download.
- Handler quan sát state `SENDING_DOWNLOAD`.
- Thành công hoặc lỗi nghiệp vụ quay lại `IDLE`.
- Framing/socket lỗi đóng session.
- Download chỉ log thành công sau ACK checksum cuối.
- Client mới vẫn kết nối được sau một phiên Download lỗi.

#### A4. Test và merge

Chạy test Download/logger riêng, sau đó toàn bộ `pytest`. PR có base
`feat/python-server-integration`. Sau review, dùng squash merge để giữ lịch sử
integration gọn.

### Pha B - Hợp nhất và sửa Upload

#### B1. Tạo branch leader-owned

Sau khi logging sạch đã merge, tạo `fix/python-upload-integration` từ
`feat/python-server-integration` mới nhất. Không tiếp tục phát triển trên
branch TV2 cũ.

#### B2. Chọn client Upload

Dùng implementation của ba commit TV3 `e6746f4`, `1d83271`, `c4d8b8e` làm nền,
sau đó review lại:

- Source phải là regular file.
- Remote filename được validate bằng codec chung.
- Dùng config chunk/max payload.
- ACK đầu phải là `ACK(FILE_UPLOAD, 0)`.
- ACK cuối phải là `ACK(FILE_CHECKSUM, bytes_sent)`.
- Server `ERROR` giữ nguyên error code.
- File thay đổi kích thước giữa lúc đọc làm session bị abort an toàn.
- Workflow trả `UploadResult`, CLI chỉ chịu trách nhiệm hiển thị.

#### B3. Viết lại adapter server Upload

Public API bắt buộc:

```python
def handle_upload(session: ServerSession, frame: Frame) -> UploadTransferResult:
    ...
```

Handler phải:

1. Parse `FILE_UPLOAD` bằng max payload từ session config.
2. Dùng `session.config.server.storage_directory`.
3. Từ chối file đích hoặc `.part` đã tồn tại với `FILE_EXISTS`.
4. Không xóa hoặc ghi đè file cũ.
5. Tạo `.part` theo chế độ exclusive.
6. Chỉ nhận `FILE_CHUNK` và `FILE_CHECKSUM` trong
   `RECEIVING_UPLOAD`.
7. Kiểm tra offset liên tục, chunk size và tổng byte không vượt declared size.
8. Đối chiếu `FILE_UPLOAD.total_size`, byte thực nhận và
   `FILE_CHECKSUM.final_size`.
9. Kiểm tra SHA-256.
10. Publish file nguyên tử và không ghi đè.
11. Xóa `.part` khi lỗi, checksum sai, size sai, offset sai hoặc client ngắt.
12. Trả kết quả có cấu trúc để logger ghi đúng filename, byte, duration,
    speed, checksum và result.

Error code bắt buộc:

- File trùng: `FILE_EXISTS`.
- Filename sai: `INVALID_FILENAME`.
- Offset sai: `OFFSET_MISMATCH`.
- Size sai: `SIZE_MISMATCH`.
- Checksum sai: `CHECKSUM_MISMATCH`.
- Quyền truy cập: `ACCESS_DENIED`.
- File I/O: `FILE_IO_ERROR`.
- Message đúng framing nhưng sai state: `INVALID_STATE`.

#### B4. Xóa implementation trùng

Sau khi module mới hoạt động, xóa hoặc ngừng sử dụng hoàn toàn:

- `src/hcmus_socket/client_upload.py`.
- `src/hcmus_socket/server_upload.py`.

Không để code cũ và code mới cùng tồn tại.

#### B5. Test Upload qua application thật

Test phải chạy:

```text
ClientSession.connect
  -> preface
  -> FILE_UPLOAD
  -> ServerSession.serve
  -> dispatcher
  -> RECEIVING_UPLOAD
  -> handle_upload
  -> IDLE
  -> LIST
  -> DISCONNECT
```

Không chấp nhận test chỉ gọi handler thủ công làm bằng chứng integration.

### Pha C - Composition root và state machine

#### C1. Server registry cuối

Server phải có đúng một handler cho mỗi request:

```python
{
    Opcode.FILE_LIST: handle_file_list,
    Opcode.FILE_UPLOAD: handle_upload,
    Opcode.FILE_DOWNLOAD: handle_download,
    Opcode.DISCONNECT: handle_disconnect,
}
```

TV1 phải chọn một cơ chế duy nhất: built-in registry trong `ServerSession` hoặc
registry được truyền từ `server/app.py`. Không đăng ký trùng và không cho test
override tùy ý các invariant như LIST/DISCONNECT.

#### C2. Client registry cuối

```python
{
    CommandName.LIST: handle_list,
    CommandName.UPLOAD: handle_upload,
    CommandName.DOWNLOAD: handle_download,
}
```

Ba lệnh dùng chung một `ClientSession`.

#### C3. State cuối

```text
LIST:       IDLE -> IDLE
UPLOAD:     IDLE -> RECEIVING_UPLOAD -> IDLE
DOWNLOAD:   IDLE -> SENDING_DOWNLOAD -> IDLE
DISCONNECT: IDLE -> CLOSING -> CLOSED
```

Lỗi nghiệp vụ có thể phục hồi về `IDLE`. Lỗi framing nghiêm trọng và socket
mất đồng bộ phải đóng session. Sau khi session đóng, server quay lại
`accept()`.

### Pha D - End-to-end, resilience và benchmark

#### D1. Luồng demo bắt buộc

Qua TCP thật và cùng một kết nối:

```text
LIST
UPLOAD sample.bin
LIST
DOWNLOAD sample.bin
LIST
DISCONNECT
```

Xác nhận file nguồn, file server và file download có SHA-256 giống nhau.

#### D2. Ma trận kích thước

Chạy cả Upload và Download cho:

- 0 byte.
- Nhỏ hơn 1 KiB.
- 32 KiB.
- 32 KiB + 1.
- Khoảng 10 MiB.
- Trên 100 MiB, đề xuất 120 MiB.
- Binary có nhiều byte `0x00`.

Theo dõi bộ nhớ cho file lớn để chứng minh không load toàn bộ file vào RAM.

#### D3. Error và recovery

Tối thiểu:

- Command thiếu tham số hoặc không hợp lệ.
- File Download không tồn tại.
- Upload file trùng tên, file cũ giữ nguyên.
- Filename nguy hiểm.
- Offset sai.
- Size sai.
- Checksum sai.
- Client ngắt giữa Upload.
- Client ngắt giữa Download.
- 20 lần connect/disconnect.
- Client mới hoạt động sau phiên framing/transfer lỗi.
- Không còn `.part` sau mọi thất bại.

#### D4. Logging và báo cáo

Chụp/ghi lại log của ít nhất:

- Kết nối và disconnect sạch.
- LIST.
- Upload thành công và thất bại.
- Download thành công và thất bại.
- File nhỏ, khoảng 10 MiB và trên 100 MiB.

Báo cáo phải giải thích length-prefixed framing, chunking, checksum, state
machine, cleanup `.part`, recovery và kết quả benchmark ba kích thước.

### Pha E - Quality gate và merge main

Trước PR cuối, TV1 phải chạy:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q

cmake -S . -B build-msvc
cmake --build build-msvc --config Debug
ctest --test-dir build-msvc -C Debug --output-on-failure

cmake --build build-msvc --config Release
ctest --test-dir build-msvc -C Release --output-on-failure
```

Đồng thời:

- Chạy hai console command thật.
- Kiểm tra `git diff --check`.
- Không commit config cá nhân, log, build output, `.part` hoặc file benchmark.
- PR cuối có reviewer; leader không tự merge PR của mình khi chưa review.
- Chỉ merge `feat/python-server-integration -> main` khi toàn bộ quality gate
  pass.

## 6. Cấu trúc file mục tiêu

```text
src/hcmus_socket/
|-- client/
|   |-- app.py
|   |-- commands.py
|   |-- session.py
|   |-- listing.py
|   |-- upload.py
|   `-- download.py
|-- server/
|   |-- app.py
|   |-- session.py
|   |-- listing.py
|   |-- upload.py
|   |-- download.py
|   `-- logger.py
|-- config.py
|-- protocol.py
|-- framing.py
|-- messages.py

tests/
|-- test_client_listing.py
|-- test_server_listing.py
|-- test_client_upload.py
|-- test_server_upload.py
|-- test_upload_end_to_end.py
|-- test_client_download.py
|-- test_server_download.py
|-- test_download_end_to_end.py
|-- test_server_logger.py
|-- test_server_logging_integration.py
|-- test_phase1_end_to_end.py
`-- test_server_recovery.py
```

## 7. Definition of Done cho integration

Integration chỉ hoàn thành khi tất cả điều sau đúng:

- `hcmus-socket-server config/app.ini` chạy được.
- `hcmus-socket-client config/app.ini` chạy được.
- LIST, Upload và Download chạy qua server application thật.
- Ba lệnh chạy liên tiếp trên cùng một TCP session.
- File nguồn/server/download có checksum khớp.
- File trùng không bị ghi đè.
- `.part` luôn được dọn sau lỗi.
- Server không crash hoặc treo khi client ngắt giữa transfer.
- Server nhận client mới sau phiên lỗi.
- File trên 100 MiB được stream với mức dùng RAM không tăng theo kích thước
  toàn file.
- Log đáp ứng R1.4 và dễ parse.
- Có benchmark ít nhất ba kích thước cho báo cáo R1.6.
- Toàn bộ `pytest` pass.
- C++ Debug và Release build, `ctest` pass.
- PR integration được review và merge vào `main`.

Tại thời điểm cập nhật, mọi tiêu chí kỹ thuật phía local đã pass. Tiêu chí
review/merge `main` là bước quản trị Git còn lại.
