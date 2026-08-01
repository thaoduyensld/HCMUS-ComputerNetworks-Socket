# Quy trình Git giai đoạn 1

## 1. Nguyên tắc

- `main` luôn build và test được.
- Không push trực tiếp lên `main`.
- Không dùng branch dài hạn theo tên thành viên.
- Mỗi branch chỉ giải quyết một task hoặc một vertical slice rõ ràng.
- Mỗi Pull Request cần ít nhất một reviewer.
- Thay đổi protocol cần sự đồng ý của cả ba thành viên.

## 2. Tên branch

```text
chore/project-foundation
feat/protocol-framing
feat/server-session-list
feat/upload-checksum
feat/download-client-logging
test/large-file
fix/disconnect-upload
docs/phase1-report
```

Branch nên tồn tại tối đa một ngày trong kế hoạch bốn ngày.

## 3. Pull Request

Mỗi PR phải:

- Gắn issue hoặc mô tả task.
- Nêu module bị ảnh hưởng.
- Nêu có thay đổi wire protocol hay không.
- Ghi các bước build/test đã chạy.
- Không chứa build output, config cá nhân, log hoặc file test lớn.
- Được cập nhật từ `main` trước khi merge nếu có xung đột.

Khuyến nghị dùng squash merge.

## 4. Review rotation

| Phần chính | Primary | Reviewer | Tester |
|---|---|---|---|
| Protocol, session, LIST | Thành viên 1 | Thành viên 3 | Thành viên 2 |
| Upload, chunking, SHA-256 | Thành viên 2 | Thành viên 1 | Thành viên 3 |
| Download, CLI, logging | Thành viên 3 | Thành viên 2 | Thành viên 1 |

Leader không tự merge PR của mình khi chưa có reviewer.

## 5. Mốc tích hợp bốn ngày

### Ngày 1

- Merge foundation và protocol.
- Client/Server build được.
- Preface, framing, kết nối và LIST hoạt động.

### Ngày 2

- Upload/download file nhỏ.
- SHA-256 khớp.
- File trùng tên bị reject.

### Ngày 3

- File 10 MiB và trên 100 MiB.
- Ngắt kết nối, checksum mismatch, logging.
- Feature freeze cuối ngày.

### Ngày 4

- Regression test.
- Benchmark và báo cáo.
- Demo rehearsal.
- Tag `phase1-v1.0`.

## 6. Giờ tích hợp

Cả nhóm thống nhất hai mốc mỗi ngày:

- Giữa ngày: cập nhật tiến độ, báo blocker và merge phần ổn định.
- Cuối ngày: review, smoke test và chốt trạng thái `main`.

Không để branch riêng đến cuối ngày 3 mới tích hợp.

## 7. Protocol freeze

Sau khi `docs/PROTOCOL.md` được duyệt:

- Không đổi opcode hoặc kích thước trường.
- Không đổi ý nghĩa `LENGTH`.
- Không đổi byte order.
- Không đổi checksum.

Thay đổi bắt buộc phải cập nhật tài liệu, Client, Server và test cùng lúc.
