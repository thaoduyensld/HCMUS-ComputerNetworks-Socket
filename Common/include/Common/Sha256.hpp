#pragma once
#include <Common/Protocol.hpp>
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>

namespace hcmus::socket {
class Sha256 final {
public:
    Sha256();
    ~Sha256();
    Sha256(const Sha256&) = delete;
    Sha256& operator=(const Sha256&) = delete;
    void update(const void* data, std::size_t size);
    [[nodiscard]] std::array<std::uint8_t, protocol::kSha256DigestBytes> finish();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
