#include <Common/Config.hpp>
#include <Common/Protocol.hpp>

#include <algorithm>
#include <charconv>
#include <fstream>
#include <limits>
#include <string_view>
#include <system_error>
#include <unordered_set>

namespace hcmus::socket {
namespace {

constexpr std::size_t kMinimumPayloadBytes = 1;
constexpr std::size_t kMaximumPayloadBytes = 16U * 1024U * 1024U;

[[nodiscard]] std::string_view trim(std::string_view value) {
    constexpr std::string_view whitespace{" \t\r\n"};
    const auto first = value.find_first_not_of(whitespace);
    if (first == std::string_view::npos) {
        return {};
    }

    const auto last = value.find_last_not_of(whitespace);
    return value.substr(first, last - first + 1);
}

[[noreturn]] void fail(
    const std::filesystem::path& path,
    const std::size_t line_number,
    const std::string& message
) {
    std::string location = path.string();
    if (line_number != 0) {
        location += ':' + std::to_string(line_number);
    }
    throw ConfigError(location + ": " + message);
}

template <typename Integer>
[[nodiscard]] Integer parse_integer(
    const std::filesystem::path& path,
    const std::size_t line_number,
    const std::string_view key,
    const std::string_view text,
    const Integer minimum,
    const Integer maximum
) {
    Integer value{};
    const auto* begin = text.data();
    const auto* end = begin + text.size();
    const auto result = std::from_chars(begin, end, value);

    if (result.ec != std::errc{} || result.ptr != end) {
        fail(path, line_number, "invalid integer for '" + std::string(key) + "'");
    }
    if (value < minimum || value > maximum) {
        fail(
            path,
            line_number,
            "'" + std::string(key) + "' is outside the allowed range"
        );
    }
    return value;
}

void assign_value(
    AppConfig& config,
    const std::filesystem::path& path,
    const std::size_t line_number,
    const std::string_view section,
    const std::string_view key,
    const std::string_view value
) {
    if (value.empty()) {
        fail(path, line_number, "'" + std::string(key) + "' cannot be empty");
    }

    if (section == "server") {
        if (key == "bind_address") {
            config.server.bind_address = value;
        } else if (key == "port") {
            config.server.port = parse_integer<std::uint16_t>(
                path, line_number, key, value, 1, 65535
            );
        } else if (key == "storage_directory") {
            config.server.storage_directory = std::string(value);
        } else {
            fail(path, line_number, "unknown key 'server." + std::string(key) + "'");
        }
        return;
    }

    if (section == "client") {
        if (key == "server_address") {
            config.client.server_address = value;
        } else if (key == "server_port") {
            config.client.server_port = parse_integer<std::uint16_t>(
                path, line_number, key, value, 1, 65535
            );
        } else if (key == "connect_timeout_ms") {
            config.client.connect_timeout_ms = parse_integer<std::uint32_t>(
                path, line_number, key, value, 1, 300000
            );
        } else if (key == "download_directory") {
            config.client.download_directory = std::string(value);
        } else {
            fail(path, line_number, "unknown key 'client." + std::string(key) + "'");
        }
        return;
    }

    if (section == "network") {
        if (key == "max_payload_bytes") {
            config.network.max_payload_bytes = parse_integer<std::size_t>(
                path,
                line_number,
                key,
                value,
                kMinimumPayloadBytes,
                kMaximumPayloadBytes
            );
        } else if (key == "chunk_size_bytes") {
            config.network.chunk_size_bytes = parse_integer<std::size_t>(
                path, line_number, key, value, 4096U, 64U * 1024U
            );
        } else {
            fail(path, line_number, "unknown key 'network." + std::string(key) + "'");
        }
        return;
    }

    fail(path, line_number, "unknown section '[" + std::string(section) + "]'");
}

}  // namespace

AppConfig load_config(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input.is_open()) {
        fail(path, 0, "cannot open config file");
    }

    AppConfig config;
    std::string section;
    std::string line;
    std::size_t line_number = 0;
    std::unordered_set<std::string> assigned_keys;

    while (std::getline(input, line)) {
        ++line_number;
        const auto content = trim(line);
        if (content.empty() || content.front() == '#' || content.front() == ';') {
            continue;
        }

        if (content.front() == '[') {
            if (content.size() < 3 || content.back() != ']') {
                fail(path, line_number, "malformed section header");
            }
            section = std::string(trim(content.substr(1, content.size() - 2)));
            if (section.empty()) {
                fail(path, line_number, "section name cannot be empty");
            }
            if (section != "server" && section != "client" && section != "network") {
                fail(path, line_number, "unknown section '[" + section + "]'");
            }
            continue;
        }

        if (section.empty()) {
            fail(path, line_number, "key-value pair must be inside a section");
        }

        const auto separator = content.find('=');
        if (separator == std::string_view::npos) {
            fail(path, line_number, "expected 'key = value'");
        }

        const auto key = trim(content.substr(0, separator));
        const auto value = trim(content.substr(separator + 1));
        if (key.empty()) {
            fail(path, line_number, "key cannot be empty");
        }

        const auto qualified_key = section + '.' + std::string(key);
        if (!assigned_keys.insert(qualified_key).second) {
            fail(path, line_number, "duplicate key '" + qualified_key + "'");
        }

        assign_value(config, path, line_number, section, key, value);
    }

    if (input.bad()) {
        fail(path, line_number, "error while reading config file");
    }

    const auto minimum_payload_for_chunk =
        protocol::kChunkOffsetBytes + config.network.chunk_size_bytes;
    if (config.network.max_payload_bytes < minimum_payload_for_chunk) {
        fail(
            path,
            0,
            "network.max_payload_bytes must be at least "
                "network.chunk_size_bytes + 8"
        );
    }

    return config;
}

}  // namespace hcmus::socket
