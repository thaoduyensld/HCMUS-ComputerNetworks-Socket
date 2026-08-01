#include <Common/Config.hpp>

#include <cstdlib>
#include <exception>
#include <filesystem>
#include <iostream>

int main(const int argc, const char* const argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: HcmusSocketClient <config-path>\n";
        return EXIT_FAILURE;
    }

    try {
        const auto config =
            hcmus::socket::load_config(std::filesystem::path{argv[1]});
        std::cout << "Client foundation ready for "
                  << config.client.server_address << ':'
                  << config.client.server_port << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "Client configuration error: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
