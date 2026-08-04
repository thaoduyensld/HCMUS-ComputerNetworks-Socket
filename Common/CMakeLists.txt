add_library(
    Common
    STATIC
        src/Config.cpp
        src/Framing.cpp
        src/Messages.cpp
        src/Socket.cpp
        src/Sha256.cpp
)

add_library(HcmusSocket::Common ALIAS Common)

target_include_directories(
    Common
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:include>"
)

target_compile_features(Common PUBLIC cxx_std_17)
hcmus_socket_enable_warnings(Common)

if(WIN32)
    target_link_libraries(Common PUBLIC ws2_32 bcrypt)
else()
    message(FATAL_ERROR "The current socket foundation requires Winsock on Windows")
endif()

if(BUILD_TESTING)
    add_subdirectory(tests)
endif()
