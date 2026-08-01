add_executable(
    HcmusSocketClient
    src/main.cpp
)

target_link_libraries(
    HcmusSocketClient
    PRIVATE
        HcmusSocket::Common
)

target_compile_features(HcmusSocketClient PRIVATE cxx_std_17)
hcmus_socket_enable_warnings(HcmusSocketClient)
