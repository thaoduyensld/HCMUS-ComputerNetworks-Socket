#pragma once

#include <Common/Framing.hpp>

#include <cstdint>
#include <array>
#include <stdexcept>
#include <string>
#include <vector>

namespace hcmus::socket::protocol {

class MessageError final : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct Acknowledgement {
    Opcode acknowledged_opcode{};
    std::uint64_t next_offset{};
};

struct ErrorMessage {
    Opcode failed_opcode{};
    ErrorCode error_code{};
    std::string message;
};

struct FileRequest { std::string filename; std::uint64_t offset{}; };
struct FileInfo { std::string filename; std::uint64_t total_size{}; std::uint64_t start_offset{}; };
struct FileChunk { std::uint64_t offset{}; std::vector<std::uint8_t> data; };
struct FileChecksum { std::uint64_t final_size{}; std::array<std::uint8_t, kSha256DigestBytes> digest{}; };

[[nodiscard]] bool is_supported_opcode(Opcode opcode) noexcept;
[[nodiscard]] bool is_supported_opcode_value(std::uint16_t opcode) noexcept;
void validate_message(const Frame& frame);

[[nodiscard]] Frame make_file_list_frame();
[[nodiscard]] Frame make_disconnect_frame();
[[nodiscard]] Frame make_acknowledgement_frame(const Acknowledgement& message);
[[nodiscard]] Acknowledgement parse_acknowledgement(const Frame& frame);
[[nodiscard]] Frame make_error_frame(const ErrorMessage& message);
[[nodiscard]] ErrorMessage parse_error(const Frame& frame);
[[nodiscard]] Frame make_file_download_frame(const FileRequest& message);
[[nodiscard]] FileRequest parse_file_download(const Frame& frame);
[[nodiscard]] Frame make_file_info_frame(const FileInfo& message);
[[nodiscard]] FileInfo parse_file_info(const Frame& frame);
[[nodiscard]] Frame make_file_chunk_frame(const FileChunk& message);
[[nodiscard]] FileChunk parse_file_chunk(const Frame& frame);
[[nodiscard]] Frame make_file_checksum_frame(const FileChecksum& message);
[[nodiscard]] FileChecksum parse_file_checksum(const Frame& frame);

}  // namespace hcmus::socket::protocol
