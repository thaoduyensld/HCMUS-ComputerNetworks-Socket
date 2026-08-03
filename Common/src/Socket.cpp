#include <Common/Socket.hpp>

#include <algorithm>
#include <limits>
#include <utility>

namespace hcmus::socket {
namespace {

[[nodiscard]] std::string socket_error_message(
    const std::string& operation,
    const int error_code
) {
    return operation + " failed with Winsock error " + std::to_string(error_code);
}

[[nodiscard]] int chunk_size(const std::size_t remaining) noexcept {
    constexpr auto maximum = static_cast<std::size_t>((std::numeric_limits<int>::max)());
    return static_cast<int>((std::min)(remaining, maximum));
}

}  // namespace

SocketError::SocketError(std::string operation, const int error_code)
    : std::runtime_error(socket_error_message(operation, error_code)),
      error_code_(error_code),
      operation_(std::move(operation)) {}

int SocketError::error_code() const noexcept { return error_code_; }

const std::string& SocketError::operation() const noexcept { return operation_; }

ConnectionClosedError::ConnectionClosedError(
    std::string context,
    const std::size_t received,
    const std::size_t expected
)
    : std::runtime_error(
          "peer closed while receiving " + context + " (received "
          + std::to_string(received) + " of " + std::to_string(expected) + " bytes)"
      ),
      received_(received),
      expected_(expected) {}

std::size_t ConnectionClosedError::received() const noexcept { return received_; }

std::size_t ConnectionClosedError::expected() const noexcept { return expected_; }

WinsockRuntime::WinsockRuntime() {
    WSADATA data{};
    const int result = WSAStartup(MAKEWORD(2, 2), &data);
    if (result != 0) {
        throw SocketError("WSAStartup(2.2)", result);
    }
    if (LOBYTE(data.wVersion) != 2 || HIBYTE(data.wVersion) != 2) {
        WSACleanup();
        throw std::runtime_error("WSAStartup returned an unsupported Winsock version");
    }
}

WinsockRuntime::~WinsockRuntime() { WSACleanup(); }

Socket::Socket(const SOCKET handle) noexcept : handle_(handle) {}

Socket::~Socket() { reset(); }

Socket::Socket(Socket&& other) noexcept : handle_(other.release()) {}

Socket& Socket::operator=(Socket&& other) noexcept {
    if (this != &other) {
        reset(other.release());
    }
    return *this;
}

bool Socket::valid() const noexcept { return handle_ != INVALID_SOCKET; }

Socket::operator bool() const noexcept { return valid(); }

SOCKET Socket::native_handle() const noexcept { return handle_; }

SOCKET Socket::release() noexcept {
    const SOCKET result = handle_;
    handle_ = INVALID_SOCKET;
    return result;
}

void Socket::reset(const SOCKET handle) noexcept {
    if (handle_ != INVALID_SOCKET) {
        closesocket(handle_);
    }
    handle_ = handle;
}

void send_all(const SOCKET socket, const void* data, const std::size_t size) {
    const auto* bytes = static_cast<const char*>(data);
    std::size_t sent = 0;
    while (sent < size) {
        const int result = send(socket, bytes + sent, chunk_size(size - sent), 0);
        if (result == SOCKET_ERROR) {
            throw SocketError("send_all/send", WSAGetLastError());
        }
        if (result == 0) {
            throw std::runtime_error("send_all/send made no progress");
        }
        sent += static_cast<std::size_t>(result);
    }
}

bool recv_exact(
    const SOCKET socket,
    void* data,
    const std::size_t size,
    const std::string& context
) {
    auto* bytes = static_cast<char*>(data);
    std::size_t received = 0;
    while (received < size) {
        const int result = recv(socket, bytes + received, chunk_size(size - received), 0);
        if (result == SOCKET_ERROR) {
            throw SocketError("recv_exact/recv for " + context, WSAGetLastError());
        }
        if (result == 0) {
            if (received == 0) {
                return false;
            }
            throw ConnectionClosedError(context, received, size);
        }
        received += static_cast<std::size_t>(result);
    }
    return true;
}

}  // namespace hcmus::socket
