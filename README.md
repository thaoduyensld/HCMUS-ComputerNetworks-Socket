# HCMUS Computer Networks — Socket File Transfer

Đồ án Client–Server truyền file qua TCP cho môn Mạng máy tính (HCMUS), được
viết bằng Python. Hệ thống hỗ trợ nhiều client đồng thời, đăng nhập bằng
username, vùng lưu trữ riêng theo người dùng, truyền file theo chunk, SHA-256,
resume sau gián đoạn, progress và giới hạn băng thông theo từng phiên.

## Chức năng chính

- Protocol nhị phân v2 với connection preface và frame có length prefix.
- `LIST`, `UPLOAD`, `DOWNLOAD` qua TCP; không nạp toàn bộ file vào RAM.
- Server thread-per-client, giới hạn bằng `server.max_clients`.
- Username duy nhất trong các phiên đang hoạt động và namespace riêng.
- Resume Upload/Download bằng offset cùng metadata kiểm chứng.
- SHA-256 ở cả hai phía trước khi công bố file hoàn chỉnh.
- Khóa theo `(namespace, filename)` để tránh transfer cùng file bị race.
- Token bucket giới hạn băng thông độc lập cho từng client.
- Server log dạng JSON Lines, an toàn khi ghi từ nhiều worker.
- Client dòng lệnh và desktop UI Tkinter có progress/cancel, theme và hai kiểu
  hiển thị danh sách file.

## Yêu cầu

- Python 3.11 trở lên.
- Tkinter để chạy desktop UI. Bản cài Python chính thức trên Windows thường đã
  bao gồm Tkinter.
- Không có dependency runtime bên thứ ba; `pytest` chỉ cần cho kiểm thử.

## Cài đặt

Từ thư mục gốc repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item config/app.example.ini config/app.ini
```

Trên Linux/macOS, kích hoạt môi trường bằng `source .venv/bin/activate` và sao
chép config bằng `cp config/app.example.ini config/app.ini`.

## Chạy chương trình

Mở server trước:

```powershell
hcmus-socket-server config/app.ini
```

Chạy client dòng lệnh ở terminal khác:

```powershell
hcmus-socket-client config/app.ini --username alice
```

Các lệnh trong client là:

```text
LIST
UPLOAD <đường-dẫn-file-local>
DOWNLOAD <tên-file-trên-server>
QUIT
```

Hoặc mở desktop UI:

```powershell
hcmus-socket-ui
```

Có thể dùng `python -m hcmus_socket.ui` nếu chưa cài entry point. UI điền sẵn
`127.0.0.1:4567`; host và port được nhập ở màn hình kết nối, còn nơi lưu file
được chọn trong hộp thoại Download.

## Cấu hình

File mẫu [`config/app.example.ini`](config/app.example.ini) chạy được ngay trên
máy local. File `config/app.ini` là cấu hình cá nhân và đã được Git bỏ qua.

Các nhóm cấu hình:

- `[server]`: địa chỉ bind, port, storage, số client tối đa và TTL file partial.
- `[client]`: địa chỉ server, timeout và thư mục download.
- `[network]`: payload tối đa, chunk size và giới hạn KiB/s mỗi client.
- `[auth]`: độ dài username tối đa.

Chi tiết validation nằm trong [`config/README.md`](config/README.md).

## Kiểm thử

Chạy toàn bộ bộ test:

```powershell
python -m pytest -q
```

Bộ test bao phủ framing, message codec, config, client/server session, LIST,
Upload/Download, checksum, namespace, concurrency, lifecycle, resume,
throttling, logging và desktop UI. CI chạy trên Windows và Ubuntu với Python
3.11–3.12.

Các demo/benchmark qua TCP loopback thật:

```powershell
python scripts/benchmark_phase1.py
python scripts/phase2_large_resume.py
python scripts/phase2_load_resilience.py
python scripts/phase2_throttling_benchmark.py
```

Mỗi script hỗ trợ `--help` và ghi artifact vào `runtime/`; thư mục này không
được commit hoặc đưa vào gói source nộp bài.

## Cấu trúc repository

```text
.
├── config/                  # Config mẫu và mô tả schema
├── docs/                    # Protocol, kiến trúc, test plan, demo, benchmark
├── scripts/                 # Benchmark và demo Phase 2
├── src/hcmus_socket/
│   ├── client/              # Session, API, CLI, LIST/UPLOAD/DOWNLOAD
│   ├── common/              # Tiện ích partial transfer dùng chung
│   ├── server/              # Listener, worker, session, storage, log
│   ├── ui/                  # Desktop UI Tkinter
│   ├── config.py            # Dataclass và parser INI nghiêm ngặt
│   ├── framing.py           # TCP framing/send/receive
│   ├── messages.py          # Encode/decode payload
│   ├── protocol.py          # Constant, opcode, error code
│   └── throttling.py        # Token bucket theo session
├── tests/                   # Unit, integration và end-to-end tests
├── pyproject.toml           # Package metadata và CLI entry points
└── README.md
```

## Tài liệu

- [`docs/PHASE2_PROTOCOL.md`](docs/PHASE2_PROTOCOL.md): đặc tả protocol v2 dùng
  bởi phiên bản nộp cuối.
- [`docs/PROTOCOL.md`](docs/PROTOCOL.md): protocol nền tảng và tương thích từ
  Phase 1.
- [`docs/architecture.md`](docs/architecture.md): kiến trúc module, concurrency,
  storage và lifecycle.
- [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md): ma trận kiểm thử và tiêu chí release.
- [`docs/PHASE2_DEMO.md`](docs/PHASE2_DEMO.md): cách chạy demo tải, resume,
  resilience và throttling.
- [`docs/PHASE1_BENCHMARK.md`](docs/PHASE1_BENCHMARK.md): kết quả benchmark file
  nhỏ, trung bình và lớn.

Các tài liệu có tiền tố `PHASE1` được giữ làm bằng chứng cho mốc phát triển đầu;
`PHASE2_PROTOCOL.md`, tài liệu kiến trúc và code hiện tại là chuẩn cho bản nộp
cuối.

## Checklist nộp bài

1. Chạy `python -m pytest -q` trên commit định nộp.
2. Kiểm tra `git status` không có source thay đổi ngoài ý muốn.
3. Không đưa `.venv/`, `build/`, `runtime/`, cache, config cá nhân hoặc file test
   lớn vào ZIP.
4. Trong video, thể hiện server, ít nhất hai client khác username, namespace,
   Upload/Download, checksum/progress và một tình huống resume hoặc giới hạn
   client/băng thông.
5. Ghi commit SHA hoặc tag release trong báo cáo và tên file nộp.
