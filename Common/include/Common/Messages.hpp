#pragma once

#include <Common/Framing.hpp>

#include <cstdint>
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

[[nodiscard]] bool is_supported_opcode(Opcode opcode) noexcept;
[[nodiscard]] bool is_supported_opcode_value(std::uint16_t opcode) noexcept;
void validate_message(const Frame& frame);

[[nodiscard]] Frame make_file_list_frame();
[[nodiscard]] Frame make_disconnect_frame();
[[nodiscard]] Frame make_acknowledgement_frame(const Acknowledgement& message);
[[nodiscard]] Acknowledgement parse_acknowledgement(const Frame& frame);
[[nodiscard]] Frame make_error_frame(const ErrorMessage& message);
[[nodiscard]] ErrorMessage parse_error(const Frame& frame);

}  // namespace hcmus::socket::protocol
