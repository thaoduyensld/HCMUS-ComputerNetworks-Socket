#include <Common/Config.hpp>

#include <cstdlib>
#include <exception>
#include <filesystem>
#include <iostream>

int main(const int argc, const char* const argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: HcmusSocketServer <config-path>\n";
        return EXIT_FAILURE;
    }

    try {
        const auto config =
            hcmus::socket::load_config(std::filesystem::path{argv[1]});
        std::cout << "Server foundation ready on "
                  << config.server.bind_address << ':'
                  << config.server.port << " with storage "
                  << config.server.storage_directory.string() << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "Server configuration error: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
