#include <Common/Messages.hpp>

#include <limits>

namespace hcmus::socket::protocol {

bool is_supported_opcode(const Opcode opcode) noexcept {
    return opcode == Opcode::acknowledgement || opcode == Opcode::error
        || opcode == Opcode::file_list || opcode == Opcode::disconnect;
}

bool is_supported_opcode_value(const std::uint16_t opcode) noexcept {
    return is_supported_opcode(static_cast<Opcode>(opcode));
}

void validate_message(const Frame& frame) {
    if (!is_supported_opcode(frame.opcode)) {
        throw MessageError("unsupported opcode in foundation message");
    }
    if ((frame.opcode == Opcode::file_list || frame.opcode == Opcode::disconnect)
        && !frame.payload.empty()) {
        throw MessageError("FILE_LIST and DISCONNECT payloads must be empty");
    }
    if (frame.opcode == Opcode::acknowledgement && frame.payload.size() != 10) {
        throw MessageError("ACK payload must contain exactly 10 bytes");
    }
    if (frame.opcode == Opcode::error) {
        if (frame.payload.size() < 6) {
            throw MessageError("ERROR payload must contain at least 6 bytes");
        }
        const auto message_size = decode_uint16(frame.payload.data() + 4);
        if (frame.payload.size() != 6U + message_size) {
            throw MessageError("ERROR message_length does not match payload size");
        }
    }
}

Frame make_file_list_frame() { return {Opcode::file_list, 0, {}}; }

Frame make_disconnect_frame() { return {Opcode::disconnect, 0, {}}; }

Frame make_acknowledgement_frame(const Acknowledgement& message) {
    Frame frame{Opcode::acknowledgement, 0, std::vector<std::uint8_t>(10)};
    encode_uint16(static_cast<std::uint16_t>(message.acknowledged_opcode), frame.payload.data());
    encode_uint64(message.next_offset, frame.payload.data() + 2);
    return frame;
}

Acknowledgement parse_acknowledgement(const Frame& frame) {
    validate_message(frame);
    if (frame.opcode != Opcode::acknowledgement) {
        throw MessageError("expected ACK frame");
    }
    return {static_cast<Opcode>(decode_uint16(frame.payload.data())),
            decode_uint64(frame.payload.data() + 2)};
}

Frame make_error_frame(const ErrorMessage& message) {
    if (message.message.size() > (std::numeric_limits<std::uint16_t>::max)()) {
        throw MessageError("ERROR message exceeds uint16 message_length");
    }
    Frame frame{Opcode::error, 0, std::vector<std::uint8_t>(6 + message.message.size())};
    encode_uint16(static_cast<std::uint16_t>(message.failed_opcode), frame.payload.data());
    encode_uint16(static_cast<std::uint16_t>(message.error_code), frame.payload.data() + 2);
    encode_uint16(static_cast<std::uint16_t>(message.message.size()), frame.payload.data() + 4);
    for (std::size_t i = 0; i < message.message.size(); ++i) {
        frame.payload[6 + i] = static_cast<std::uint8_t>(message.message[i]);
    }
    return frame;
}

ErrorMessage parse_error(const Frame& frame) {
    validate_message(frame);
    if (frame.opcode != Opcode::error) {
        throw MessageError("expected ERROR frame");
    }
    return {
        static_cast<Opcode>(decode_uint16(frame.payload.data())),
        static_cast<ErrorCode>(decode_uint16(frame.payload.data() + 2)),
        std::string(frame.payload.begin() + 6, frame.payload.end())
    };
}

}  // namespace hcmus::socket::protocol
