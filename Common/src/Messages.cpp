#include <Common/Messages.hpp>

#include <limits>
#include <algorithm>

namespace hcmus::socket::protocol {

bool is_supported_opcode(const Opcode opcode) noexcept {
    return opcode == Opcode::acknowledgement || opcode == Opcode::error
        || opcode == Opcode::file_list || opcode == Opcode::disconnect
        || opcode == Opcode::file_download || opcode == Opcode::file_info
        || opcode == Opcode::file_chunk || opcode == Opcode::file_checksum;
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
    if (frame.opcode == Opcode::file_download && frame.payload.size() < 10) throw MessageError("FILE_DOWNLOAD payload too short");
    if (frame.opcode == Opcode::file_info && frame.payload.size() < 18) throw MessageError("FILE_INFO payload too short");
    if (frame.opcode == Opcode::file_chunk && frame.payload.size() < 9) throw MessageError("FILE_CHUNK must contain offset and data");
    if (frame.opcode == Opcode::file_checksum && frame.payload.size() != 40) throw MessageError("FILE_CHECKSUM payload must contain exactly 40 bytes");
}

namespace {
void validate_name(const std::string& name) {
    if (name.empty() || name.size() > kMaximumFilenameBytes || name == "." || name == ".."
        || name.find('/') != std::string::npos || name.find('\\') != std::string::npos
        || name.find('\0') != std::string::npos) throw MessageError("invalid filename");
}
std::string read_name(const Frame& frame, std::size_t trailer) {
    if (frame.payload.size() < 2 + trailer) throw MessageError("filename payload too short");
    const auto n = decode_uint16(frame.payload.data());
    if (n == 0 || n > kMaximumFilenameBytes || frame.payload.size() != 2U + n + trailer) throw MessageError("invalid filename length");
    std::string name(frame.payload.begin() + 2, frame.payload.begin() + 2 + n);
    validate_name(name); return name;
}
void write_name(std::vector<std::uint8_t>& payload, const std::string& name) {
    validate_name(name); encode_uint16(static_cast<std::uint16_t>(name.size()), payload.data());
    std::copy(name.begin(), name.end(), payload.begin() + 2);
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

Frame make_file_download_frame(const FileRequest& m) {
    Frame f{Opcode::file_download, 0, std::vector<std::uint8_t>(2 + m.filename.size() + 8)};
    write_name(f.payload, m.filename); encode_uint64(m.offset, f.payload.data() + 2 + m.filename.size()); return f;
}
FileRequest parse_file_download(const Frame& f) {
    if (f.opcode != Opcode::file_download) throw MessageError("expected FILE_DOWNLOAD");
    const auto name = read_name(f, 8); return {name, decode_uint64(f.payload.data() + 2 + name.size())};
}
Frame make_file_info_frame(const FileInfo& m) {
    Frame f{Opcode::file_info, 0, std::vector<std::uint8_t>(2 + m.filename.size() + 16)};
    write_name(f.payload, m.filename); auto* p = f.payload.data() + 2 + m.filename.size(); encode_uint64(m.total_size, p); encode_uint64(m.start_offset, p + 8); return f;
}
FileInfo parse_file_info(const Frame& f) {
    if (f.opcode != Opcode::file_info) throw MessageError("expected FILE_INFO");
    const auto name = read_name(f, 16); const auto* p = f.payload.data() + 2 + name.size(); return {name, decode_uint64(p), decode_uint64(p + 8)};
}
Frame make_file_chunk_frame(const FileChunk& m) {
    if (m.data.empty()) throw MessageError("FILE_CHUNK data cannot be empty");
    Frame f{Opcode::file_chunk, 0, std::vector<std::uint8_t>(8 + m.data.size())}; encode_uint64(m.offset, f.payload.data()); std::copy(m.data.begin(), m.data.end(), f.payload.begin() + 8); return f;
}
FileChunk parse_file_chunk(const Frame& f) {
    validate_message(f); if (f.opcode != Opcode::file_chunk) throw MessageError("expected FILE_CHUNK");
    return {decode_uint64(f.payload.data()), std::vector<std::uint8_t>(f.payload.begin() + 8, f.payload.end())};
}
Frame make_file_checksum_frame(const FileChecksum& m) {
    Frame f{Opcode::file_checksum, 0, std::vector<std::uint8_t>(40)}; encode_uint64(m.final_size, f.payload.data()); std::copy(m.digest.begin(), m.digest.end(), f.payload.begin() + 8); return f;
}
FileChecksum parse_file_checksum(const Frame& f) {
    validate_message(f); if (f.opcode != Opcode::file_checksum) throw MessageError("expected FILE_CHECKSUM");
    FileChecksum m; m.final_size = decode_uint64(f.payload.data()); std::copy(f.payload.begin() + 8, f.payload.end(), m.digest.begin()); return m;
}

}  // namespace hcmus::socket::protocol
