# Client

Target `HcmusSocketClient` liên kết với `HcmusSocket::Common`.

Phạm vi giai đoạn 1:

- Đọc config và kết nối Server.
- Xác nhận connection preface.
- Parse đúng ba lệnh `LIST`, `UPLOAD`, `DOWNLOAD`.
- Điều phối transfer theo `docs/PROTOCOL.md`.
- Ghi download vào file `.part` và chỉ công nhận sau SHA-256.

Client hiện kết nối thật, xác nhận preface, parse CLI và thực hiện DOWNLOAD theo
chunk vào file `.part`. File chỉ được đổi tên sau khi kích thước và SHA-256 khớp.
`LIST` và `UPLOAD` được giữ ở CLI để tích hợp handler của thành viên 1 và 2.
