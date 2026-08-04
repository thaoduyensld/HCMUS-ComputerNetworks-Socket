#include <Server/ServerApp.hpp>

int main(const int argc, char** argv) {
    return hcmus::socket::server::run(argc, argv);
}
