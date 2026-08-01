#include <Common/Config.hpp>
#include <Common/Protocol.hpp>

#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>

namespace {

bool expect(const bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAILED: " << message << '\n';
    }
    return condition;
}

bool rejects_invalid_config() {
    const auto path =
        std::filesystem::temp_directory_path() / "hcmus_socket_invalid_config.ini";

    {
        std::ofstream output(path);
        if (!output) {
            std::cerr << "FAILED: could not create invalid config fixture\n";
            return false;
        }
        output << "[unsupported]\n";
    }

    bool rejected = false;
    try {
        static_cast<void>(hcmus::socket::load_config(path));
    } catch (const hcmus::socket::ConfigError&) {
        rejected = true;
    }

    std::error_code error;
    std::filesystem::remove(path, error);
    return expect(rejected, "unknown section must be rejected");
}

bool rejects_payload_smaller_than_chunk() {
    const auto path =
        std::filesystem::temp_directory_path() / "hcmus_socket_small_payload.ini";

    {
        std::ofstream output(path);
        if (!output) {
            std::cerr << "FAILED: could not create payload fixture\n";
            return false;
        }
        output << "[network]\n"
               << "max_payload_bytes = 4096\n"
               << "chunk_size_bytes = 4096\n";
    }

    bool rejected = false;
    try {
        static_cast<void>(hcmus::socket::load_config(path));
    } catch (const hcmus::socket::ConfigError&) {
        rejected = true;
    }

    std::error_code error;
    std::filesystem::remove(path, error);
    return expect(
        rejected,
        "payload must include the chunk offset and chunk data"
    );
}

}  // namespace

int main(const int argc, const char* const argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: CommonTests <config-path>\n";
        return EXIT_FAILURE;
    }

    try {
        const auto config = hcmus::socket::load_config(std::filesystem::path{argv[1]});

        bool passed = true;
        passed &= expect(config.server.bind_address == "0.0.0.0", "server bind address");
        passed &= expect(config.server.port == 4567, "server port");
        passed &= expect(
            config.server.storage_directory == "runtime/server_storage",
            "server storage directory"
        );
        passed &= expect(config.client.server_address == "127.0.0.1", "server address");
        passed &= expect(config.client.server_port == 4567, "client server port");
        passed &= expect(config.client.connect_timeout_ms == 5000, "connect timeout");
        passed &= expect(
            config.client.download_directory == "runtime/client_downloads",
            "client download directory"
        );
        passed &= expect(config.network.max_payload_bytes == 1048576, "payload limit");
        passed &= expect(config.network.chunk_size_bytes == 32768, "chunk size");
        passed &= expect(
            hcmus::socket::protocol::kMagic == 0x48434D55U,
            "protocol magic"
        );
        passed &= expect(hcmus::socket::protocol::kVersion == 1, "protocol version");
        passed &= expect(
            hcmus::socket::protocol::kConnectionPrefaceBytes == 8,
            "connection preface size"
        );
        passed &= expect(
            hcmus::socket::protocol::kFrameHeaderBytes == 8,
            "frame header size"
        );
        passed &= expect(
            static_cast<std::uint16_t>(
                hcmus::socket::protocol::Opcode::file_upload
            ) == 0x0012,
            "upload opcode"
        );
        passed &= expect(
            static_cast<std::uint16_t>(
                hcmus::socket::protocol::ErrorCode::file_exists
            ) == 0x0011,
            "file exists error code"
        );
        passed &= rejects_invalid_config();
        passed &= rejects_payload_smaller_than_chunk();

        return passed ? EXIT_SUCCESS : EXIT_FAILURE;
    } catch (const std::exception& error) {
        std::cerr << "FAILED: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
