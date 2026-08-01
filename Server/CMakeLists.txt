add_executable(
    HcmusSocketServer
    src/main.cpp
)

target_link_libraries(
    HcmusSocketServer
    PRIVATE
        HcmusSocket::Common
)

target_compile_features(HcmusSocketServer PRIVATE cxx_std_17)
hcmus_socket_enable_warnings(HcmusSocketServer)
