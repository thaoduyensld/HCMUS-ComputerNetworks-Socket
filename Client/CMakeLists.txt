add_executable(
    HcmusSocketClient
    include/Client/ClientApp.hpp
    src/ClientApp.cpp
    src/main.cpp
)

target_include_directories(HcmusSocketClient PRIVATE include)

target_link_libraries(
    HcmusSocketClient
    PRIVATE
        HcmusSocket::Common
)

target_compile_features(HcmusSocketClient PRIVATE cxx_std_17)
hcmus_socket_enable_warnings(HcmusSocketClient)
