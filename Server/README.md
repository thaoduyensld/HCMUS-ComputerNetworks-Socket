# Server

Target `HcmusSocketServer` liên kết với `HcmusSocket::Common`.

Phạm vi giai đoạn 1:

- Lắng nghe TCP và phục vụ tuần tự một client.
- Xác nhận connection preface.
- Quản lý state machine và dispatch opcode.
- Quản lý storage root, file `.part` và chính sách reject file trùng.
- Ghi log lệnh, thời gian, tốc độ và kết quả checksum.

Entry point hiện chỉ xác nhận config để giữ foundation build được. Listener và
request handlers sẽ được triển khai trong feature branch.
