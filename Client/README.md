# Client

Target `HcmusSocketClient` liên kết với `HcmusSocket::Common`.

Phạm vi giai đoạn 1:

- Đọc config và kết nối Server.
- Xác nhận connection preface.
- Parse đúng ba lệnh `LIST`, `UPLOAD`, `DOWNLOAD`.
- Điều phối transfer theo `docs/PROTOCOL.md`.
- Ghi download vào file `.part` và chỉ công nhận sau SHA-256.

Entry point hiện chỉ xác nhận config để giữ foundation build được. Socket và
command handlers sẽ được triển khai trong feature branch.
