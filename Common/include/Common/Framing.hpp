#pragma once

#include <Common/Protocol.hpp>
#include <Common/Socket.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace hcmus::socket::protocol {

enum class FramingErrorCode {
    truncated_frame,
    invalid_length,
    payload_too_large,
    invalid_user_id,
    unsupported_opcode,
    invalid_preface_magic,
    invalid_preface_version,
    invalid_preface_reserved,
};

class FramingError final : public std::runtime_error {
public:
    FramingError(FramingErrorCode code, std::string message);
    [[nodiscard]] FramingErrorCode code() const noexcept;

private:
    FramingErrorCode code_;
};

struct ConnectionPreface {
    std::uint32_t magic{kMagic};
    std::uint16_t version{kVersion};
    std::uint16_t reserved{0};
};

struct Frame {
    Opcode opcode{};
    std::uint16_t user_id{kPhaseOneUserId};
    std::vector<std::uint8_t> payload;
};

void encode_uint16(std::uint16_t value, std::uint8_t* output) noexcept;
void encode_uint32(std::uint32_t value, std::uint8_t* output) noexcept;
void encode_uint64(std::uint64_t value, std::uint8_t* output) noexcept;
[[nodiscard]] std::uint16_t decode_uint16(const std::uint8_t* input) noexcept;
[[nodiscard]] std::uint32_t decode_uint32(const std::uint8_t* input) noexcept;
[[nodiscard]] std::uint64_t decode_uint64(const std::uint8_t* input) noexcept;

[[nodiscard]] std::array<std::uint8_t, kConnectionPrefaceBytes> encode_preface(
    const ConnectionPreface& preface = {}
);
[[nodiscard]] ConnectionPreface decode_preface(
    const std::array<std::uint8_t, kConnectionPrefaceBytes>& bytes
);
void validate_preface(const ConnectionPreface& preface);

[[nodiscard]] std::vector<std::uint8_t> serialize_frame(
    const Frame& frame,
    std::size_t max_payload_bytes = kDefaultMaxPayloadBytes
);
[[nodiscard]] Frame deserialize_frame(
    const std::vector<std::uint8_t>& bytes,
    std::size_t max_payload_bytes = kDefaultMaxPayloadBytes
);
void send_frame(
    SOCKET socket,
    const Frame& frame,
    std::size_t max_payload_bytes = kDefaultMaxPayloadBytes
);
[[nodiscard]] std::optional<Frame> receive_frame(
    SOCKET socket,
    std::size_t max_payload_bytes = kDefaultMaxPayloadBytes
);

}  // namespace hcmus::socket::protocol
