add_executable(CommonTests CommonTests.cpp)
target_link_libraries(CommonTests PRIVATE HcmusSocket::Common)
hcmus_socket_enable_warnings(CommonTests)

add_test(
    NAME Common.ConfigExample
    COMMAND CommonTests "${PROJECT_SOURCE_DIR}/config/app.example.ini"
)
