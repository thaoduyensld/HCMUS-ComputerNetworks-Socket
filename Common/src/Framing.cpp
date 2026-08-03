#include <Common/Framing.hpp>
#include <Common/Messages.hpp>

#include <algorithm>
#include <limits>
#include <utility>

namespace hcmus::socket::protocol {
namespace {

void validate_header(
    const std::uint32_t length,
    const std::uint16_t opcode,
    const std::uint16_t user_id,
    const std::size_t max_payload_bytes
) {
    if (length < kFrameBodyHeaderBytes) {
        throw FramingError(
            FramingErrorCode::invalid_length,
            "frame LENGTH " + std::to_string(length) + " is smaller than 4"
        );
    }
    const auto payload_size = static_cast<std::size_t>(length - kFrameBodyHeaderBytes);
    if (payload_size > max_payload_bytes) {
        throw FramingError(
            FramingErrorCode::payload_too_large,
            "frame payload " + std::to_string(payload_size) + " exceeds maximum "
                + std::to_string(max_payload_bytes)
        );
    }
    if (user_id != kPhaseOneUserId) {
        throw FramingError(
            FramingErrorCode::invalid_user_id,
            "frame USER_ID " + std::to_string(user_id) + " must be 0 in phase 1"
        );
    }
    if (!is_supported_opcode_value(opcode)) {
        throw FramingError(
            FramingErrorCode::unsupported_opcode,
            "frame opcode " + std::to_string(opcode) + " is unsupported"
        );
    }
}

[[noreturn]] void rethrow_truncated(
    const ConnectionClosedError& error,
    const std::string& part
) {
    throw FramingError(
        FramingErrorCode::truncated_frame,
        "truncated frame " + part + ": " + error.what()
    );
}

}  // namespace

FramingError::FramingError(FramingErrorCode code, std::string message)
    : std::runtime_error(std::move(message)), code_(code) {}

FramingErrorCode FramingError::code() const noexcept { return code_; }

void encode_uint16(const std::uint16_t value, std::uint8_t* output) noexcept {
    output[0] = static_cast<std::uint8_t>(value >> 8U);
    output[1] = static_cast<std::uint8_t>(value);
}

void encode_uint32(const std::uint32_t value, std::uint8_t* output) noexcept {
    for (std::size_t i = 0; i < 4; ++i) {
        output[i] = static_cast<std::uint8_t>(value >> ((3U - i) * 8U));
    }
}

void encode_uint64(const std::uint64_t value, std::uint8_t* output) noexcept {
    for (std::size_t i = 0; i < 8; ++i) {
        output[i] = static_cast<std::uint8_t>(value >> ((7U - i) * 8U));
    }
}

std::uint16_t decode_uint16(const std::uint8_t* input) noexcept {
    return static_cast<std::uint16_t>(
        (static_cast<std::uint16_t>(input[0]) << 8U) | input[1]
    );
}

std::uint32_t decode_uint32(const std::uint8_t* input) noexcept {
    std::uint32_t value = 0;
    for (std::size_t i = 0; i < 4; ++i) {
        value = (value << 8U) | input[i];
    }
    return value;
}

std::uint64_t decode_uint64(const std::uint8_t* input) noexcept {
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < 8; ++i) {
        value = (value << 8U) | input[i];
    }
    return value;
}

std::array<std::uint8_t, kConnectionPrefaceBytes> encode_preface(
    const ConnectionPreface& preface
) {
    std::array<std::uint8_t, kConnectionPrefaceBytes> result{};
    encode_uint32(preface.magic, result.data());
    encode_uint16(preface.version, result.data() + 4);
    encode_uint16(preface.reserved, result.data() + 6);
    return result;
}

ConnectionPreface decode_preface(
    const std::array<std::uint8_t, kConnectionPrefaceBytes>& bytes
) {
    return {decode_uint32(bytes.data()), decode_uint16(bytes.data() + 4),
            decode_uint16(bytes.data() + 6)};
}

void validate_preface(const ConnectionPreface& preface) {
    if (preface.magic != kMagic) {
        throw FramingError(FramingErrorCode::invalid_preface_magic, "invalid preface MAGIC");
    }
    if (preface.version != kVersion) {
        throw FramingError(
            FramingErrorCode::invalid_preface_version,
            "unsupported preface VERSION " + std::to_string(preface.version)
        );
    }
    if (preface.reserved != 0) {
        throw FramingError(
            FramingErrorCode::invalid_preface_reserved,
            "preface RESERVED must be 0"
        );
    }
}

std::vector<std::uint8_t> serialize_frame(
    const Frame& frame,
    const std::size_t max_payload_bytes
) {
    validate_message(frame);
    if (frame.payload.size() > max_payload_bytes
        || frame.payload.size() > (std::numeric_limits<std::uint32_t>::max)() - 4U) {
        throw FramingError(FramingErrorCode::payload_too_large, "frame payload is too large");
    }
    validate_header(
        static_cast<std::uint32_t>(kFrameBodyHeaderBytes + frame.payload.size()),
        static_cast<std::uint16_t>(frame.opcode), frame.user_id, max_payload_bytes
    );

    std::vector<std::uint8_t> result(kFrameHeaderBytes + frame.payload.size());
    encode_uint32(
        static_cast<std::uint32_t>(kFrameBodyHeaderBytes + frame.payload.size()),
        result.data()
    );
    encode_uint16(static_cast<std::uint16_t>(frame.opcode), result.data() + 4);
    encode_uint16(frame.user_id, result.data() + 6);
    std::copy(frame.payload.begin(), frame.payload.end(), result.begin() + 8);
    return result;
}

Frame deserialize_frame(
    const std::vector<std::uint8_t>& bytes,
    const std::size_t max_payload_bytes
) {
    if (bytes.size() < kFrameHeaderBytes) {
        throw FramingError(FramingErrorCode::truncated_frame, "frame header is truncated");
    }
    const auto length = decode_uint32(bytes.data());
    const auto opcode = decode_uint16(bytes.data() + 4);
    const auto user_id = decode_uint16(bytes.data() + 6);
    validate_header(length, opcode, user_id, max_payload_bytes);
    const auto total_size = kLengthFieldBytes + static_cast<std::size_t>(length);
    if (bytes.size() != total_size) {
        throw FramingError(
            FramingErrorCode::truncated_frame,
            "serialized frame size does not match LENGTH"
        );
    }
    Frame frame{static_cast<Opcode>(opcode), user_id, {}};
    frame.payload.assign(bytes.begin() + 8, bytes.end());
    validate_message(frame);
    return frame;
}

void send_frame(
    const SOCKET socket,
    const Frame& frame,
    const std::size_t max_payload_bytes
) {
    const auto bytes = serialize_frame(frame, max_payload_bytes);
    send_all(socket, bytes.data(), bytes.size());
}

std::optional<Frame> receive_frame(
    const SOCKET socket,
    const std::size_t max_payload_bytes
) {
    std::array<std::uint8_t, kLengthFieldBytes> length_bytes{};
    try {
        if (!recv_exact(socket, length_bytes.data(), length_bytes.size(), "frame LENGTH")) {
            return std::nullopt;
        }
    } catch (const ConnectionClosedError& error) {
        rethrow_truncated(error, "LENGTH");
    }

    const auto length = decode_uint32(length_bytes.data());
    if (length < kFrameBodyHeaderBytes) {
        validate_header(length, 0, 0, max_payload_bytes);
    }
    const auto payload_size = static_cast<std::size_t>(length - kFrameBodyHeaderBytes);
    if (payload_size > max_payload_bytes) {
        throw FramingError(
            FramingErrorCode::payload_too_large,
            "frame payload " + std::to_string(payload_size) + " exceeds maximum "
                + std::to_string(max_payload_bytes)
        );
    }

    std::array<std::uint8_t, kFrameBodyHeaderBytes> header{};
    try {
        if (!recv_exact(socket, header.data(), header.size(), "frame header")) {
            throw FramingError(
                FramingErrorCode::truncated_frame,
                "peer closed after frame LENGTH and before OPCODE/USER_ID"
            );
        }
    } catch (const ConnectionClosedError& error) {
        rethrow_truncated(error, "header");
    }
    const auto opcode = decode_uint16(header.data());
    const auto user_id = decode_uint16(header.data() + 2);
    validate_header(length, opcode, user_id, max_payload_bytes);

    Frame frame{static_cast<Opcode>(opcode), user_id, {}};
    frame.payload.resize(payload_size);
    if (payload_size != 0) {
        try {
            if (!recv_exact(socket, frame.payload.data(), payload_size, "frame payload")) {
                throw FramingError(
                    FramingErrorCode::truncated_frame,
                    "peer closed before frame payload"
                );
            }
        } catch (const ConnectionClosedError& error) {
            rethrow_truncated(error, "payload");
        }
    }
    validate_message(frame);
    return frame;
}

}  // namespace hcmus::socket::protocol
