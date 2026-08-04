#include <Server/ServerApp.hpp>
#include <Common/Config.hpp>
#include <Common/Framing.hpp>
#include <Common/Messages.hpp>
#include <Common/Sha256.hpp>
#include <Common/Socket.hpp>
#include <ws2tcpip.h>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <vector>

namespace fs = std::filesystem;
using namespace hcmus::socket;
using namespace hcmus::socket::protocol;

namespace {
class Logger {
public:
    explicit Logger(const fs::path& root) { fs::create_directories(root); out_.open(root / "server.log", std::ios::app); }
    void transfer(const std::string& ip, const std::string& file, std::uint64_t bytes,
                  std::chrono::steady_clock::time_point start, const std::string& result,
                  const std::string& error = "none", const std::string& checksum = "n/a") {
        const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        const auto ms = (std::max<std::int64_t>)(1, std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count());
        const double speed = static_cast<double>(bytes) * 1000.0 / 1024.0 / static_cast<double>(ms);
        std::tm tm{}; localtime_s(&tm, &now);
        out_ << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S") << " client=" << ip
             << " command=DOWNLOAD file=\"" << file << "\" bytes=" << bytes
             << " duration_ms=" << ms << " speed_kbps=" << std::fixed << std::setprecision(2) << speed
             << " result=" << result << " error=" << error << " checksum=" << checksum << '\n'; out_.flush();
    }
private: std::ofstream out_;
};

void send_preface(SOCKET s) { const auto p = encode_preface(); send_all(s, p.data(), p.size()); }
bool receive_preface(SOCKET s) { std::array<std::uint8_t, kConnectionPrefaceBytes> p{}; if (!recv_exact(s, p.data(), p.size(), "connection preface")) return false; validate_preface(decode_preface(p)); return true; }

void send_error(SOCKET s, Opcode op, ErrorCode code, const std::string& text, std::size_t max) {
    send_frame(s, make_error_frame({op, code, text}), max);
}

void download(SOCKET s, const Frame& request_frame, const AppConfig& cfg, const std::string& ip, Logger& logger) {
    const auto start = std::chrono::steady_clock::now(); std::string name; std::uint64_t sent = 0;
    try {
        const auto request = parse_file_download(request_frame); name = request.filename;
        if (request.offset != 0) { send_error(s, request_frame.opcode, ErrorCode::invalid_payload, "requested_offset must be zero", cfg.network.max_payload_bytes); logger.transfer(ip,name,0,start,"failure","INVALID_PAYLOAD"); return; }
        const fs::path path = cfg.server.storage_directory / fs::path(name);
        if (!fs::exists(path) || !fs::is_regular_file(path)) { send_error(s, request_frame.opcode, ErrorCode::file_not_found, "file not found", cfg.network.max_payload_bytes); logger.transfer(ip,name,0,start,"failure","FILE_NOT_FOUND"); return; }
        const auto total = fs::file_size(path); std::ifstream input(path, std::ios::binary);
        if (!input) { send_error(s, request_frame.opcode, ErrorCode::access_denied, "cannot open file", cfg.network.max_payload_bytes); logger.transfer(ip,name,0,start,"failure","ACCESS_DENIED"); return; }
        send_frame(s, make_file_info_frame({name,total,0}), cfg.network.max_payload_bytes);
        auto response = receive_frame(s, cfg.network.max_payload_bytes);
        if (!response || response->opcode != Opcode::acknowledgement || parse_acknowledgement(*response).acknowledged_opcode != Opcode::file_info) throw std::runtime_error("FILE_INFO was not acknowledged");
        Sha256 hash; std::vector<std::uint8_t> buffer(cfg.network.chunk_size_bytes);
        while (input) {
            input.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(buffer.size())); const auto count = input.gcount(); if (count <= 0) break;
            std::vector<std::uint8_t> data(buffer.begin(), buffer.begin() + count); hash.update(data.data(), data.size());
            send_frame(s, make_file_chunk_frame({sent, std::move(data)}), cfg.network.max_payload_bytes); sent += static_cast<std::uint64_t>(count);
        }
        if (input.bad() || sent != total) throw std::runtime_error("file read failed");
        send_frame(s, make_file_checksum_frame({total, hash.finish()}), cfg.network.max_payload_bytes);
        response = receive_frame(s, cfg.network.max_payload_bytes);
        if (!response || response->opcode != Opcode::acknowledgement) throw std::runtime_error("checksum was not acknowledged");
        const auto ack = parse_acknowledgement(*response);
        if (ack.acknowledged_opcode != Opcode::file_checksum || ack.next_offset != total) throw std::runtime_error("invalid final acknowledgement");
        logger.transfer(ip,name,sent,start,"success","none","match");
    } catch (const std::exception& e) { logger.transfer(ip,name,sent,start,"failure",e.what()); throw; }
}

void session(SOCKET s, const AppConfig& cfg, const std::string& ip, Logger& logger) {
    if (!receive_preface(s)) return; send_preface(s);
    while (auto frame = receive_frame(s, cfg.network.max_payload_bytes)) {
        if (frame->opcode == Opcode::disconnect) { send_frame(s, make_acknowledgement_frame({Opcode::disconnect,0}), cfg.network.max_payload_bytes); return; }
        if (frame->opcode == Opcode::file_download) { download(s,*frame,cfg,ip,logger); continue; }
        send_error(s, frame->opcode, ErrorCode::unsupported_opcode, "command is not implemented on this branch", cfg.network.max_payload_bytes);
    }
}
}

int hcmus::socket::server::run(int argc, char** argv) {
    if (argc != 2) { std::cerr << "Usage: HcmusSocketServer <config-path>\n"; return EXIT_FAILURE; }
    try {
        const auto cfg = load_config(argv[1]); WinsockRuntime winsock; fs::create_directories(cfg.server.storage_directory); Logger logger(cfg.server.storage_directory);
        Socket listener(::socket(AF_INET,SOCK_STREAM,IPPROTO_TCP)); if (!listener) throw SocketError("socket",WSAGetLastError());
        BOOL reuse=TRUE; setsockopt(listener.native_handle(),SOL_SOCKET,SO_REUSEADDR,reinterpret_cast<const char*>(&reuse),sizeof(reuse));
        sockaddr_in address{}; address.sin_family=AF_INET; address.sin_port=htons(cfg.server.port);
        if (inet_pton(AF_INET,cfg.server.bind_address.c_str(),&address.sin_addr)!=1) throw std::runtime_error("invalid server.bind_address");
        if (bind(listener.native_handle(),reinterpret_cast<sockaddr*>(&address),sizeof(address))==SOCKET_ERROR) throw SocketError("bind",WSAGetLastError());
        if (listen(listener.native_handle(),SOMAXCONN)==SOCKET_ERROR) throw SocketError("listen",WSAGetLastError());
        std::cout << "Listening on " << cfg.server.bind_address << ':' << cfg.server.port << '\n';
        for (;;) { sockaddr_in peer{}; int n=sizeof(peer); Socket client(accept(listener.native_handle(),reinterpret_cast<sockaddr*>(&peer),&n)); if (!client) throw SocketError("accept",WSAGetLastError()); char ip[INET_ADDRSTRLEN]{}; inet_ntop(AF_INET,&peer.sin_addr,ip,sizeof(ip)); try { session(client.native_handle(),cfg,ip,logger); } catch(const std::exception& e) { std::cerr << "Client " << ip << ": " << e.what() << '\n'; } }
    } catch(const std::exception& e) { std::cerr << "Server error: " << e.what() << '\n'; return EXIT_FAILURE; }
}
