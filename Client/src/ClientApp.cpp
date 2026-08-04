#include <Client/ClientApp.hpp>
#include <Common/Config.hpp>
#include <Common/Framing.hpp>
#include <Common/Messages.hpp>
#include <Common/Sha256.hpp>
#include <Common/Socket.hpp>
#include <ws2tcpip.h>
#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>

namespace fs = std::filesystem;
using namespace hcmus::socket;
using namespace hcmus::socket::protocol;

namespace {
Socket connect_server(const AppConfig& cfg) {
    Socket socket_handle(socket(AF_INET,SOCK_STREAM,IPPROTO_TCP)); if (!socket_handle) throw SocketError("socket",WSAGetLastError());
    sockaddr_in address{}; address.sin_family=AF_INET; address.sin_port=htons(cfg.client.server_port);
    if (inet_pton(AF_INET,cfg.client.server_address.c_str(),&address.sin_addr)!=1) throw std::runtime_error("invalid client.server_address");
    if (connect(socket_handle.native_handle(),reinterpret_cast<sockaddr*>(&address),sizeof(address))==SOCKET_ERROR) throw SocketError("connect",WSAGetLastError());
    const auto preface=encode_preface(); send_all(socket_handle.native_handle(),preface.data(),preface.size());
    std::array<std::uint8_t,kConnectionPrefaceBytes> reply{}; if (!recv_exact(socket_handle.native_handle(),reply.data(),reply.size(),"server preface")) throw std::runtime_error("server closed during preface"); validate_preface(decode_preface(reply));
    return socket_handle;
}

void print_error(const Frame& frame) { const auto e=parse_error(frame); std::cerr << "Server error (" << static_cast<unsigned>(e.error_code) << "): " << e.message << '\n'; }

void download(SOCKET socket_handle, const AppConfig& cfg, const std::string& name) {
    const fs::path final_path=cfg.client.download_directory/fs::path(name), part_path=final_path.string()+".part";
    if (fs::exists(final_path)) { std::cerr << "Local file already exists: " << final_path.string() << '\n'; return; }
    if (fs::exists(part_path)) {
        std::error_code cleanup_error; fs::remove(part_path, cleanup_error);
        if (cleanup_error) throw std::runtime_error("cannot remove stale download .part file");
    }
    send_frame(socket_handle,make_file_download_frame({name,0}),cfg.network.max_payload_bytes);
    auto frame=receive_frame(socket_handle,cfg.network.max_payload_bytes); if (!frame) throw std::runtime_error("server closed before FILE_INFO");
    if (frame->opcode==Opcode::error) { print_error(*frame); return; }
    const auto info=parse_file_info(*frame); if (info.filename!=name || info.start_offset!=0) throw std::runtime_error("invalid FILE_INFO metadata");
    fs::create_directories(cfg.client.download_directory); std::ofstream output(part_path,std::ios::binary|std::ios::trunc); if(!output) throw std::runtime_error("cannot create download .part file");
    bool committed=false;
    try {
        send_frame(socket_handle,make_acknowledgement_frame({Opcode::file_info,0}),cfg.network.max_payload_bytes);
        Sha256 hash; std::uint64_t received=0; int last_percent=-1;
        for (;;) {
            frame=receive_frame(socket_handle,cfg.network.max_payload_bytes); if(!frame) throw std::runtime_error("server disconnected during download");
            if(frame->opcode==Opcode::error) { print_error(*frame); throw std::runtime_error("server rejected download"); }
            if(frame->opcode==Opcode::file_chunk) {
                const auto chunk=parse_file_chunk(*frame); if(chunk.offset!=received || received+chunk.data.size()>info.total_size) throw std::runtime_error("invalid chunk offset or size");
                output.write(reinterpret_cast<const char*>(chunk.data.data()),static_cast<std::streamsize>(chunk.data.size())); if(!output) throw std::runtime_error("cannot write download file"); hash.update(chunk.data.data(),chunk.data.size()); received+=chunk.data.size();
                const auto percent=info.total_size==0?100:static_cast<int>(100.0*static_cast<double>(received)/static_cast<double>(info.total_size)); if(percent!=last_percent){std::cout << "\rDownloading " << name << ": " << percent << "%" << std::flush;last_percent=percent;} continue;
            }
            if(frame->opcode!=Opcode::file_checksum) throw std::runtime_error("unexpected frame during download");
            const auto expected=parse_file_checksum(*frame); const auto actual=hash.finish(); output.close();
            if(expected.final_size!=info.total_size || received!=info.total_size) { send_frame(socket_handle,make_error_frame({Opcode::file_checksum,ErrorCode::size_mismatch,"download size mismatch"}),cfg.network.max_payload_bytes); throw std::runtime_error("download size mismatch"); }
            if(expected.digest!=actual) { send_frame(socket_handle,make_error_frame({Opcode::file_checksum,ErrorCode::checksum_mismatch,"download checksum mismatch"}),cfg.network.max_payload_bytes); throw std::runtime_error("download checksum mismatch"); }
            fs::rename(part_path,final_path); committed=true; send_frame(socket_handle,make_acknowledgement_frame({Opcode::file_checksum,received}),cfg.network.max_payload_bytes); std::cout << "\rDownloaded " << name << " (" << received << " bytes, SHA-256 matched)\n"; return;
        }
    } catch (...) { output.close(); if(!committed) { std::error_code ignored; fs::remove(part_path,ignored); } throw; }
}

std::string upper(std::string text) { std::transform(text.begin(),text.end(),text.begin(),[](unsigned char c){return static_cast<char>(std::toupper(c));}); return text; }
void loop(SOCKET socket_handle,const AppConfig& cfg) {
    std::cout << "Commands: LIST, UPLOAD <filename>, DOWNLOAD <filename>, QUIT\n"; std::string line;
    while(std::cout << "> " && std::getline(std::cin,line)) {
        std::istringstream input(line); std::string command,arg,extra; input>>command; command=upper(command);
        if(command.empty()) continue;
        if(command=="QUIT") { if(input>>extra){std::cerr<<"QUIT takes no arguments\n";continue;} send_frame(socket_handle,make_disconnect_frame(),cfg.network.max_payload_bytes); (void)receive_frame(socket_handle,cfg.network.max_payload_bytes); return; }
        if(command=="LIST") { if(input>>extra){std::cerr<<"LIST takes no arguments\n";continue;} send_frame(socket_handle,make_file_list_frame(),cfg.network.max_payload_bytes); auto f=receive_frame(socket_handle,cfg.network.max_payload_bytes); if(f&&f->opcode==Opcode::error)print_error(*f); else std::cout<<"LIST response received\n"; continue; }
        if(command=="DOWNLOAD") { if(!(input>>arg)||input>>extra){std::cerr<<"Usage: DOWNLOAD <filename>\n";continue;} try{download(socket_handle,cfg,arg);}catch(const std::exception&e){std::cerr<<"Download failed: "<<e.what()<<'\n';} continue; }
        if(command=="UPLOAD") { if(!(input>>arg)||input>>extra){std::cerr<<"Usage: UPLOAD <filename>\n";continue;} std::cerr<<"UPLOAD belongs to member 2 and is not integrated yet\n"; continue; }
        std::cerr << "Unknown command. Use LIST, UPLOAD <filename>, DOWNLOAD <filename>, or QUIT\n";
    }
}
}

int hcmus::socket::client::run(int argc,char** argv) {
    if(argc!=2){std::cerr<<"Usage: HcmusSocketClient <config-path>\n";return EXIT_FAILURE;}
    try{const auto cfg=load_config(argv[1]);WinsockRuntime winsock;auto server=connect_server(cfg);std::cout<<"Connected to "<<cfg.client.server_address<<':'<<cfg.client.server_port<<'\n';loop(server.native_handle(),cfg);return EXIT_SUCCESS;}catch(const std::exception&e){std::cerr<<"Client error: "<<e.what()<<'\n';return EXIT_FAILURE;}
}
