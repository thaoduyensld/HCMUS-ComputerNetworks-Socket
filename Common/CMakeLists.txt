add_library(
    Common
    STATIC
        src/Config.cpp
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

if(BUILD_TESTING)
    add_subdirectory(tests)
endif()
