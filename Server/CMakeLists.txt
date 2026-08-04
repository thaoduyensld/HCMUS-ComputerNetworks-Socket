add_executable(
    HcmusSocketServer
    include/Server/ServerApp.hpp
    src/ServerApp.cpp
    src/main.cpp
)

target_include_directories(HcmusSocketServer PRIVATE include)

target_link_libraries(
    HcmusSocketServer
    PRIVATE
        HcmusSocket::Common
)

target_compile_features(HcmusSocketServer PRIVATE cxx_std_17)
hcmus_socket_enable_warnings(HcmusSocketServer)
