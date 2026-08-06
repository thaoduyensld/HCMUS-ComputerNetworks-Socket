# HCMUS Computer Networks - Socket

Đồ án lập trình socket theo mô hình client-server cho môn Mạng máy tính
(HCMUS). Repository dùng C++17, CMake và tách mã dùng chung thành thư viện
`Common`.

Giai đoạn 1 phục vụ tuần tự một client và hỗ trợ đúng ba lệnh `LIST`, `UPLOAD`
và `DOWNLOAD`. Wire protocol v1 dùng connection preface, length-prefixed
framing, file chunk 32 KiB và SHA-256. File trùng tên bị từ chối.

## Yêu cầu

- CMake 3.20 trở lên.
- Trình biên dịch hỗ trợ C++17:
  - Windows: Visual Studio 2022 trở lên với workload **Desktop development
    with C++**.
  - Linux/macOS: GCC 9+, Clang 10+ hoặc tương đương.

Không cần cài thư viện bên thứ ba cho foundation hiện tại.

## Cấu trúc repository

```text
.
├── Client/                 # Executable client
├── Common/                 # Static library dùng chung
│   ├── include/Common/     # Public headers
│   ├── src/                # Implementation
│   └── tests/              # Unit/smoke tests không phụ thuộc framework
├── Server/                 # Executable server
├── cmake/                  # CMake modules dùng chung
├── config/                 # Config mẫu; config thật không commit
├── docs/                   # Tài liệu kiến trúc và quy ước
└── CMakeLists.txt          # Điểm vào build
```

## Build và test

Từ thư mục gốc của repository:

```powershell
cmake -S . -B build
cmake --build build --config Debug
ctest --test-dir build -C Debug --output-on-failure
```

Với generator single-config (Ninja/Unix Makefiles), có thể đặt build type lúc
configure:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

Để tắt test:

```bash
cmake -S . -B build -DBUILD_TESTING=OFF
```

## Cấu hình chạy

Tạo config cục bộ từ file mẫu:

```powershell
Copy-Item config/app.example.ini config/app.ini
```

`config/app.ini` bị Git bỏ qua để tránh commit nhầm thông tin theo máy. Chi
tiết các key và giá trị hợp lệ nằm tại
[`config/README.md`](config/README.md).

Client và Server cùng dùng `load_config()` để đọc file này. Có thể truyền đường
dẫn config từ CLI; `Common` không tự đọc biến môi trường để giữ hành vi dễ kiểm
thử.

## Project Common

Target CMake `Common` (alias `HcmusSocket::Common`) hiện cung cấp:

- `Common/Config.hpp`: kiểu cấu hình dùng chung và parser INI fail-fast.
- `Common/Protocol.hpp`: version, kích thước wire, opcode và error code.

Ví dụ:

```cpp
#include <Common/Config.hpp>

const auto config = hcmus::socket::load_config("config/app.ini");
const auto server_port = config.server.port;
```

Parser báo rõ file và dòng khi config sai, từ chối key/section không được hỗ
trợ và kiểm tra port, timeout, chunk size và kích thước payload.

## Tài liệu bắt buộc

- [`docs/PROTOCOL.md`](docs/PROTOCOL.md): đặc tả byte-level và sequence.
- [`docs/architecture.md`](docs/architecture.md): ranh giới module.
- [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md): ma trận kiểm thử giai đoạn 1.
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md): quy trình Git trong bốn ngày.
- [`docs/PHASE1_INTEGRATION_STATUS.md`](docs/PHASE1_INTEGRATION_STATUS.md):
  trạng thái, quyết định và quality gate tích hợp Giai đoạn 1.
- [`docs/PHASE1_BENCHMARK.md`](docs/PHASE1_BENCHMARK.md): kết quả benchmark
  Upload/Download cho 512 byte, 10 MiB và 120 MiB.

## Quy ước đóng góp

- Không commit file build, file cấu hình thật, secret hoặc file IDE theo máy.
- Mã public của `Common` đặt trong namespace `hcmus::socket`.
- Mỗi thay đổi phải build được và chạy qua `ctest`.
- Cảnh báo trình biên dịch được bật ở mức cao; code mới không nên thêm warning.
- Thay đổi wire format phải cập nhật `docs/PROTOCOL.md`.
- Không push trực tiếp lên `main`; mọi thay đổi đi qua Pull Request.

Xem thêm [`docs/architecture.md`](docs/architecture.md) để biết ranh giới giữa
`Client`, `Server` và `Common`.
