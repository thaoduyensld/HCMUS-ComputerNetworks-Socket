#pragma once

#include <cstddef>
#include <cstdint>

namespace hcmus::socket::protocol {

inline constexpr std::uint32_t kMagic = 0x48434D55U;  // "HCMU"
inline constexpr std::uint16_t kVersion = 1;
inline constexpr std::uint16_t kPhaseOneUserId = 0;

inline constexpr std::size_t kConnectionPrefaceBytes = 8;
inline constexpr std::size_t kLengthFieldBytes = 4;
inline constexpr std::size_t kOpcodeFieldBytes = 2;
inline constexpr std::size_t kUserIdFieldBytes = 2;
inline constexpr std::size_t kFrameHeaderBytes =
    kLengthFieldBytes + kOpcodeFieldBytes + kUserIdFieldBytes;
inline constexpr std::size_t kFrameBodyHeaderBytes =
    kOpcodeFieldBytes + kUserIdFieldBytes;

inline constexpr std::size_t kChunkOffsetBytes = 8;
inline constexpr std::size_t kDefaultChunkBytes = 32U * 1024U;
inline constexpr std::size_t kDefaultMaxPayloadBytes = 1024U * 1024U;
inline constexpr std::size_t kMaximumFilenameBytes = 255;
inline constexpr std::size_t kSha256DigestBytes = 32;

enum class Opcode : std::uint16_t {
    disconnect = 0x0002,

    file_list = 0x0010,
    file_list_response = 0x0011,
    file_upload = 0x0012,
    file_download = 0x0013,
    file_chunk = 0x0014,
    file_delete = 0x0015,  // Reserved for phase 2.
    file_info = 0x0016,
    file_checksum = 0x0017,

    acknowledgement = 0x0020,
    error = 0x00FF,
};

enum class ErrorCode : std::uint16_t {
    invalid_frame = 0x0001,
    unsupported_opcode = 0x0002,
    invalid_payload = 0x0003,
    invalid_state = 0x0004,
    payload_too_large = 0x0005,
    invalid_user_id = 0x0006,

    file_not_found = 0x0010,
    file_exists = 0x0011,
    invalid_filename = 0x0012,
    access_denied = 0x0013,
    file_io_error = 0x0014,
    size_mismatch = 0x0015,
    checksum_mismatch = 0x0016,
    offset_mismatch = 0x0017,
    transfer_in_progress = 0x0018,
    list_too_large = 0x0019,

    internal_error = 0x00FF,
};

}  // namespace hcmus::socket::protocol
