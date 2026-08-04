#include <Common/Framing.hpp>
#include <Common/Messages.hpp>
#include <Common/Socket.hpp>

#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <future>
#include <iostream>
#include <thread>
#include <utility>
#include <vector>

namespace {

namespace protocol = hcmus::socket::protocol;
using hcmus::socket::Socket;

bool expect(const bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAILED: " << message << '\n';
    }
    return condition;
}

template <typename Function>
bool expect_framing_error(
    Function function,
    const protocol::FramingErrorCode code,
    const char* message
) {
    try {
        function();
    } catch (const protocol::FramingError& error) {
        return expect(error.code() == code, message);
    }
    return expect(false, message);
}

struct ConnectedSockets {
    Socket client;
    Socket server;
};

ConnectedSockets make_connected_sockets() {
    Socket listener{::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)};
    if (!listener) {
        throw hcmus::socket::SocketError("test socket(listener)", WSAGetLastError());
    }

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = 0;
    if (bind(
            listener.native_handle(), reinterpret_cast<const sockaddr*>(&address),
            static_cast<int>(sizeof(address))
        ) == SOCKET_ERROR) {
        throw hcmus::socket::SocketError("test bind", WSAGetLastError());
    }
    if (listen(listener.native_handle(), 1) == SOCKET_ERROR) {
        throw hcmus::socket::SocketError("test listen", WSAGetLastError());
    }

    int address_size = static_cast<int>(sizeof(address));
    if (getsockname(
            listener.native_handle(), reinterpret_cast<sockaddr*>(&address), &address_size
        ) == SOCKET_ERROR) {
        throw hcmus::socket::SocketError("test getsockname", WSAGetLastError());
    }

    Socket client{::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)};
    if (!client) {
        throw hcmus::socket::SocketError("test socket(client)", WSAGetLastError());
    }
    if (connect(
            client.native_handle(), reinterpret_cast<const sockaddr*>(&address),
            static_cast<int>(sizeof(address))
        ) == SOCKET_ERROR) {
        throw hcmus::socket::SocketError("test connect", WSAGetLastError());
    }

    Socket server{accept(listener.native_handle(), nullptr, nullptr)};
    if (!server) {
        throw hcmus::socket::SocketError("test accept", WSAGetLastError());
    }
    return {std::move(client), std::move(server)};
}

bool test_integer_codec() {
    std::array<std::uint8_t, 8> bytes{};
    protocol::encode_uint16(0xABCDU, bytes.data());
    bool passed = expect(bytes[0] == 0xABU && bytes[1] == 0xCDU, "uint16 big-endian");
    passed &= expect(protocol::decode_uint16(bytes.data()) == 0xABCDU, "uint16 round trip");
    protocol::encode_uint32(0x01234567U, bytes.data());
    passed &= expect(protocol::decode_uint32(bytes.data()) == 0x01234567U, "uint32 round trip");
    protocol::encode_uint64(0x0123456789ABCDEFULL, bytes.data());
    passed &= expect(
        protocol::decode_uint64(bytes.data()) == 0x0123456789ABCDEFULL,
        "uint64 round trip"
    );
    return passed;
}

bool test_preface() {
    const auto bytes = protocol::encode_preface();
    const auto decoded = protocol::decode_preface(bytes);
    protocol::validate_preface(decoded);
    bool passed = expect(decoded.magic == protocol::kMagic, "valid preface round trip");
    passed &= expect_framing_error(
        [] { protocol::validate_preface({0, protocol::kVersion, 0}); },
        protocol::FramingErrorCode::invalid_preface_magic, "invalid magic rejected"
    );
    passed &= expect_framing_error(
        [] { protocol::validate_preface({protocol::kMagic, 2, 0}); },
        protocol::FramingErrorCode::invalid_preface_version, "invalid version rejected"
    );
    passed &= expect_framing_error(
        [] { protocol::validate_preface({protocol::kMagic, protocol::kVersion, 1}); },
        protocol::FramingErrorCode::invalid_preface_reserved, "invalid reserved rejected"
    );
    return passed;
}

bool test_frame_codec_and_validation() {
    const auto original = protocol::make_error_frame(
        {protocol::Opcode::file_list, protocol::ErrorCode::invalid_payload,
         std::string{"binary\0message", 14}}
    );
    const auto bytes = protocol::serialize_frame(original);
    const auto decoded = protocol::deserialize_frame(bytes);
    bool passed = expect(decoded.payload == original.payload, "binary payload round trip");
    const auto error = protocol::parse_error(decoded);
    passed &= expect(error.message == std::string{"binary\0message", 14}, "embedded zero preserved");

    std::vector<std::uint8_t> invalid(8);
    protocol::encode_uint32(3, invalid.data());
    passed &= expect_framing_error(
        [&] { static_cast<void>(protocol::deserialize_frame(invalid)); },
        protocol::FramingErrorCode::invalid_length, "LENGTH below 4 rejected"
    );

    protocol::encode_uint32(9, invalid.data());
    passed &= expect_framing_error(
        [&] { static_cast<void>(protocol::deserialize_frame(invalid, 4)); },
        protocol::FramingErrorCode::payload_too_large, "oversized payload rejected"
    );

    protocol::encode_uint32(4, invalid.data());
    protocol::encode_uint16(static_cast<std::uint16_t>(protocol::Opcode::file_list), invalid.data() + 4);
    protocol::encode_uint16(1, invalid.data() + 6);
    passed &= expect_framing_error(
        [&] { static_cast<void>(protocol::deserialize_frame(invalid)); },
        protocol::FramingErrorCode::invalid_user_id, "nonzero USER_ID rejected"
    );

    protocol::encode_uint16(0x7777, invalid.data() + 4);
    protocol::encode_uint16(0, invalid.data() + 6);
    passed &= expect_framing_error(
        [&] { static_cast<void>(protocol::deserialize_frame(invalid)); },
        protocol::FramingErrorCode::unsupported_opcode, "unsupported opcode rejected"
    );
    return passed;
}

bool test_partial_and_consecutive_frames() {
    auto sockets = make_connected_sockets();
    const auto first = protocol::serialize_frame(protocol::make_error_frame(
        {protocol::Opcode::file_list, protocol::ErrorCode::invalid_payload, "abc"}
    ));
    const auto second = protocol::serialize_frame(protocol::make_file_list_frame());

    auto received_first_future = std::async(std::launch::async, [&sockets] {
        return protocol::receive_frame(sockets.server.native_handle());
    });
    hcmus::socket::send_all(sockets.client.native_handle(), first.data(), 2);
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    hcmus::socket::send_all(sockets.client.native_handle(), first.data() + 2, 5);
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    hcmus::socket::send_all(sockets.client.native_handle(), first.data() + 7, first.size() - 7);

    const auto received_first = received_first_future.get();

    std::vector<std::uint8_t> consecutive;
    consecutive.insert(consecutive.end(), second.begin(), second.end());
    consecutive.insert(consecutive.end(), second.begin(), second.end());
    hcmus::socket::send_all(
        sockets.client.native_handle(), consecutive.data(), consecutive.size()
    );
    const auto received_second = protocol::receive_frame(sockets.server.native_handle());
    const auto received_third = protocol::receive_frame(sockets.server.native_handle());
    bool passed = expect(received_first.has_value(), "split header/payload received");
    passed &= expect(received_first && received_first->payload.size() == 9, "split payload intact");
    passed &= expect(
        received_second && received_second->opcode == protocol::Opcode::file_list,
        "consecutive frames remain separate"
    );
    passed &= expect(
        received_third && received_third->opcode == protocol::Opcode::file_list,
        "second coalesced frame remains separate"
    );
    return passed;
}

bool test_disconnects() {
    bool passed = true;
    {
        auto sockets = make_connected_sockets();
        sockets.client.reset();
        passed &= expect(
            !protocol::receive_frame(sockets.server.native_handle()).has_value(),
            "clean close before frame reported"
        );
    }
    {
        auto sockets = make_connected_sockets();
        const std::array<std::uint8_t, 2> partial{{0, 0}};
        hcmus::socket::send_all(sockets.client.native_handle(), partial.data(), partial.size());
        sockets.client.reset();
        passed &= expect_framing_error(
            [&] { static_cast<void>(protocol::receive_frame(sockets.server.native_handle())); },
            protocol::FramingErrorCode::truncated_frame, "close during header reported"
        );
    }
    {
        auto sockets = make_connected_sockets();
        std::array<std::uint8_t, 10> partial{};
        protocol::encode_uint32(10, partial.data());
        protocol::encode_uint16(static_cast<std::uint16_t>(protocol::Opcode::error), partial.data() + 4);
        hcmus::socket::send_all(sockets.client.native_handle(), partial.data(), partial.size());
        sockets.client.reset();
        passed &= expect_framing_error(
            [&] { static_cast<void>(protocol::receive_frame(sockets.server.native_handle())); },
            protocol::FramingErrorCode::truncated_frame, "close during payload reported"
        );
    }
    return passed;
}

bool test_socket_move() {
    auto sockets = make_connected_sockets();
    const SOCKET original = sockets.client.native_handle();
    Socket moved{std::move(sockets.client)};
    bool passed = expect(!sockets.client.valid(), "moved-from socket invalidated");
    passed &= expect(moved.native_handle() == original, "move preserves native handle");
    Socket assigned;
    assigned = std::move(moved);
    passed &= expect(!moved.valid(), "move-assigned source invalidated");
    protocol::send_frame(assigned.native_handle(), protocol::make_file_list_frame());
    const auto frame = protocol::receive_frame(sockets.server.native_handle());
    passed &= expect(frame && frame->opcode == protocol::Opcode::file_list, "moved socket remains usable");
    return passed;
}

bool test_download_messages() {
    using namespace protocol;
    bool passed = true;
    const auto request = parse_file_download(deserialize_frame(serialize_frame(make_file_download_frame({"data.bin", 0}))));
    passed &= expect(request.filename == "data.bin" && request.offset == 0, "FILE_DOWNLOAD round trip");
    const auto info = parse_file_info(deserialize_frame(serialize_frame(make_file_info_frame({"data.bin", 100000, 0}))));
    passed &= expect(info.filename == "data.bin" && info.total_size == 100000 && info.start_offset == 0, "FILE_INFO round trip");
    const FileChunk chunk{32768, {0, 1, 2, 0, 255}};
    const auto decoded_chunk = parse_file_chunk(deserialize_frame(serialize_frame(make_file_chunk_frame(chunk))));
    passed &= expect(decoded_chunk.offset == chunk.offset && decoded_chunk.data == chunk.data, "binary FILE_CHUNK round trip");
    FileChecksum checksum; checksum.final_size = 5; checksum.digest.fill(0xA5);
    const auto decoded_checksum = parse_file_checksum(deserialize_frame(serialize_frame(make_file_checksum_frame(checksum))));
    passed &= expect(decoded_checksum.final_size == checksum.final_size && decoded_checksum.digest == checksum.digest, "FILE_CHECKSUM round trip");
    return passed;
}

}  // namespace

int main() {
    try {
        const hcmus::socket::WinsockRuntime winsock;
        bool passed = true;
        passed &= test_integer_codec();
        passed &= test_preface();
        passed &= test_frame_codec_and_validation();
        passed &= test_partial_and_consecutive_frames();
        passed &= test_disconnects();
        passed &= test_socket_move();
        passed &= test_download_messages();
        return passed ? EXIT_SUCCESS : EXIT_FAILURE;
    } catch (const std::exception& error) {
        std::cerr << "FAILED with exception: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
