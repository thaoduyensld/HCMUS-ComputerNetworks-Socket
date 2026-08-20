# Quy trình tích hợp và phát hành

## 1. Quy ước Git

- `main` luôn phải cài đặt và test được.
- Mỗi branch chỉ xử lý một thay đổi có phạm vi rõ ràng.
- Không commit config cá nhân, log, runtime data, cache, môi trường ảo hoặc file
  benchmark lớn.
- Thay đổi wire format phải cập nhật code client, code server, tài liệu protocol
  và test trong cùng một PR.
- PR cần mô tả phạm vi, ảnh hưởng protocol và các lệnh kiểm tra đã chạy.

Tên branch đề xuất:

```text
feat/<chuc-nang>
fix/<loi>
test/<pham-vi>
docs/<tai-lieu>
chore/<cong-viec>
```

## 2. Review

Người review kiểm tra tối thiểu:

1. Input từ network/filesystem được validate trước khi dùng.
2. Socket, file, lock, worker và registry entry được giải phóng ở mọi nhánh lỗi.
3. Transfer vẫn streaming và không nạp toàn bộ file vào RAM.
4. Thay đổi concurrency không tạo race hoặc giữ lock trong lúc sleep/I/O dài.
5. Test mới bao phủ success path, protocol error và disconnect.
6. README/tài liệu được cập nhật nếu lệnh chạy hoặc hành vi người dùng thay đổi.

## 3. Quality gate trước merge

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q src scripts
git diff --check
```

Sau merge, kiểm tra CI trên Windows và Ubuntu. Không tạo tag release nếu một job
CI chưa thành công.

## 4. Chốt bản nộp

1. Cập nhật `main` và xác nhận working tree không có source ngoài ý muốn.
2. Chạy full test và ít nhất một smoke test server/client thật.
3. Chạy demo cần xuất hiện trong video từ chính commit định nộp.
4. Kiểm tra config mẫu, README và các đường dẫn tài liệu.
5. Tạo ZIP chỉ từ file được Git theo dõi; không nén nguyên working directory.
6. Kiểm tra danh sách ZIP và thử cài/chạy từ thư mục giải nén mới.
7. Tạo tag annotated cho bản cuối sau khi mọi kiểm tra pass.
8. Ghi cùng commit SHA/tag vào báo cáo, video và tên gói nộp.

## 5. Nội dung video tối thiểu

- Giới thiệu kiến trúc Client–Server và protocol v2.
- Khởi động server và kết nối nhiều client khác username.
- LIST, Upload và Download với progress cùng checksum.
- Chứng minh namespace riêng hoặc cùng basename giữa hai người dùng.
- Minh họa ít nhất một khả năng Phase 2: resume, giới hạn client, resilience hoặc
  throttling.
- Kết thúc bằng kết quả test và commit SHA/tag của bản nộp.

## 6. Khi cần sửa sau khi quay

Nếu code thay đổi sau video, phải chạy lại test và xác định thay đổi có làm video
không còn phản ánh đúng bản nộp hay không. Không dùng lại tag cũ cho source mới;
tạo tag mới hoặc ghi rõ commit SHA cuối.
