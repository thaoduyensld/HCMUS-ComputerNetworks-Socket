#pragma once

#ifndef _WIN32
#error "The current socket foundation requires Winsock on Windows"
#endif

#include <winsock2.h>

#include <cstddef>
#include <stdexcept>
#include <string>

namespace hcmus::socket {

class SocketError : public std::runtime_error {
public:
    SocketError(std::string operation, int error_code);

    [[nodiscard]] int error_code() const noexcept;
    [[nodiscard]] const std::string& operation() const noexcept;

private:
    int error_code_;
    std::string operation_;
};

class ConnectionClosedError : public std::runtime_error {
public:
    ConnectionClosedError(std::string context, std::size_t received, std::size_t expected);

    [[nodiscard]] std::size_t received() const noexcept;
    [[nodiscard]] std::size_t expected() const noexcept;

private:
    std::size_t received_;
    std::size_t expected_;
};

class WinsockRuntime final {
public:
    WinsockRuntime();
    ~WinsockRuntime();

    WinsockRuntime(const WinsockRuntime&) = delete;
    WinsockRuntime& operator=(const WinsockRuntime&) = delete;
    WinsockRuntime(WinsockRuntime&&) = delete;
    WinsockRuntime& operator=(WinsockRuntime&&) = delete;
};

class Socket final {
public:
    Socket() noexcept = default;
    explicit Socket(SOCKET handle) noexcept;
    ~Socket();

    Socket(const Socket&) = delete;
    Socket& operator=(const Socket&) = delete;
    Socket(Socket&& other) noexcept;
    Socket& operator=(Socket&& other) noexcept;

    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] explicit operator bool() const noexcept;
    [[nodiscard]] SOCKET native_handle() const noexcept;
    [[nodiscard]] SOCKET release() noexcept;
    void reset(SOCKET handle = INVALID_SOCKET) noexcept;

private:
    SOCKET handle_{INVALID_SOCKET};
};

void send_all(SOCKET socket, const void* data, std::size_t size);

// Returns false only when the peer closes before any byte is received. A close
// after a partial read throws ConnectionClosedError.
[[nodiscard]] bool recv_exact(
    SOCKET socket,
    void* data,
    std::size_t size,
    const std::string& context = "TCP data"
);

}  // namespace hcmus::socket
