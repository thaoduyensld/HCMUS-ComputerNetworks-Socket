#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace hcmus::socket {

struct ServerConfig {
    std::string bind_address{"0.0.0.0"};
    std::uint16_t port{4567};
    std::filesystem::path storage_directory{"runtime/server_storage"};
};

struct ClientConfig {
    std::string server_address{"127.0.0.1"};
    std::uint16_t server_port{4567};
    std::uint32_t connect_timeout_ms{5000};
    std::filesystem::path download_directory{"runtime/client_downloads"};
};

struct NetworkConfig {
    std::size_t max_payload_bytes{1024U * 1024U};
    std::size_t chunk_size_bytes{32U * 1024U};
};

struct AppConfig {
    ServerConfig server;
    ClientConfig client;
    NetworkConfig network;
};

class ConfigError final : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Loads an INI file and validates every supported field.
// Throws ConfigError when the file cannot be read or contains invalid data.
[[nodiscard]] AppConfig load_config(const std::filesystem::path& path);

}  // namespace hcmus::socket
