# Server

Target `HcmusSocketServer` liên kết với `HcmusSocket::Common`.

Phạm vi giai đoạn 1:

- Lắng nghe TCP và phục vụ tuần tự một client.
- Xác nhận connection preface.
- Quản lý state machine và dispatch opcode.
- Quản lý storage root, file `.part` và chính sách reject file trùng.
- Ghi log lệnh, thời gian, tốc độ và kết quả checksum.

Server hiện có listener tuần tự, preface/session loop, DOWNLOAD streaming và log
có cấu trúc tại `<storage_directory>/server.log`. Handler LIST và UPLOAD sẽ được
tích hợp từ phần việc của thành viên 1 và 2.
