# Kế hoạch kiểm thử giai đoạn 1

## 1. Mục tiêu

Kiểm chứng ba lệnh cơ bản, message boundary, streaming file, SHA-256, logging và
khả năng server tiếp tục hoạt động sau lỗi.

Mỗi test cần ghi:

- Người chạy.
- Commit SHA.
- Build type.
- Hệ điều hành.
- Kích thước file.
- Kết quả.
- Log hoặc bằng chứng khi cần.

## 2. Test foundation

| ID | Test | Kết quả mong đợi |
|---|---|---|
| F01 | Configure CMake từ repository sạch | Thành công |
| F02 | Build Debug | Không warning mới |
| F03 | Build Release | Thành công |
| F04 | Chạy `ctest` | Tất cả test pass |
| F05 | Config có section lạ | Bị từ chối rõ ràng |
| F06 | Payload nhỏ hơn chunk + offset | Bị từ chối khi load config |

## 3. Test framing

| ID | Test | Kết quả mong đợi |
|---|---|---|
| P01 | Preface đúng | Server echo và phiên vào `IDLE` |
| P02 | Sai magic | Server đóng kết nối, không crash |
| P03 | Sai version | Server đóng kết nối, ghi log |
| P04 | Header đến qua nhiều lần nhận | Đọc đúng một frame |
| P05 | Payload đến qua nhiều lần nhận | Đọc đủ payload |
| P06 | Hai frame đến cùng một lần nhận | Xử lý đúng hai frame |
| P07 | `LENGTH < 4` | Đóng kết nối |
| P08 | Payload vượt giới hạn | Đóng kết nối |
| P09 | Opcode lạ | Trả `UNSUPPORTED_OPCODE` |
| P10 | User ID khác 0 | Trả `INVALID_USER_ID` |

## 4. Test chức năng

| ID | Test | Kết quả mong đợi |
|---|---|---|
| C01 | LIST thư mục rỗng | Danh sách rỗng hợp lệ |
| C02 | LIST nhiều file | Đủ tên và kích thước, sắp xếp theo tên |
| C03 | UPLOAD file mới | Thành công, checksum khớp |
| C04 | UPLOAD file trùng tên | Bị reject với `FILE_EXISTS` |
| C05 | DOWNLOAD file tồn tại | Thành công, checksum khớp |
| C06 | DOWNLOAD file không tồn tại | Trả `FILE_NOT_FOUND` |
| C07 | Tên file `..` hoặc chứa separator | Trả `INVALID_FILENAME` |
| C08 | Lệnh thiếu tham số | Client báo lỗi, không gửi request sai |
| C09 | Lệnh không hợp lệ | Client báo lỗi rõ ràng |

## 5. Ma trận kích thước file

Chạy cả upload và download cho:

| Loại | Kích thước đề xuất |
|---|---:|
| Rỗng | 0 byte |
| Nhỏ | 512 byte |
| Biên chunk | 32.768 byte |
| Qua biên chunk | 32.769 byte |
| Trung bình | Khoảng 10 MiB |
| Lớn | Trên 100 MiB, đề xuất 120 MiB |
| Nhị phân | Có nhiều byte `0x00` |

File test lớn được sinh cục bộ và không commit vào Git.

## 6. Test chịu lỗi

| ID | Test | Kết quả mong đợi |
|---|---|---|
| E01 | Kill client giữa upload | Server xóa `.part`, tiếp tục accept |
| E02 | Kill client giữa download | Hai phía đóng file an toàn |
| E03 | Làm hỏng một chunk | `CHECKSUM_MISMATCH` |
| E04 | Offset không liên tục | `OFFSET_MISMATCH` |
| E05 | Không có quyền ghi storage | `ACCESS_DENIED` hoặc `FILE_IO_ERROR` |
| E06 | Kết nối/ngắt 20 lần | Server không treo hoặc crash |
| E07 | Kết nối mới sau phiên lỗi | Client mới hoạt động bình thường |

## 7. Test tài nguyên và hiệu năng

- Theo dõi bộ nhớ khi truyền file trên 100 MiB.
- Bộ nhớ không được tăng tuyến tính theo kích thước file.
- Đo thời gian và KB/s cho tối thiểu ba kích thước.
- Log phải có timestamp, IP, command, filename, bytes, duration, speed và result.

## 8. Điều kiện release

- Debug và Release build thành công.
- Tất cả test bắt buộc pass.
- Không còn file `.part` sau test thất bại.
- File nguồn và đích có SHA-256 giống nhau.
- Server nhận được client mới sau test ngắt kết nối.
- Bảng benchmark và log đã được đưa vào báo cáo.
