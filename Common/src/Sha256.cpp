#include <Common/Sha256.hpp>
#include <windows.h>
#include <bcrypt.h>
#include <limits>
#include <stdexcept>
#include <vector>

namespace hcmus::socket {
namespace {
void check(NTSTATUS status, const char* operation) {
    if (status < 0) throw std::runtime_error(std::string(operation) + " failed");
}
}
struct Sha256::Impl {
    BCRYPT_ALG_HANDLE algorithm{};
    BCRYPT_HASH_HANDLE hash{};
    std::vector<std::uint8_t> object;
    bool finished{};
    Impl() {
        check(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0), "BCryptOpenAlgorithmProvider");
        DWORD size = 0, written = 0;
        check(BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&size), sizeof(size), &written, 0), "BCryptGetProperty");
        object.resize(size);
        check(BCryptCreateHash(algorithm, &hash, object.data(), size, nullptr, 0, 0), "BCryptCreateHash");
    }
    ~Impl() { if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0); }
};
Sha256::Sha256() : impl_(std::make_unique<Impl>()) {}
Sha256::~Sha256() = default;
void Sha256::update(const void* data, std::size_t size) {
    if (impl_->finished) throw std::logic_error("SHA-256 already finalized");
    const auto* p = static_cast<const std::uint8_t*>(data);
    while (size) {
        const auto n = static_cast<ULONG>((std::min)(size, static_cast<std::size_t>((std::numeric_limits<ULONG>::max)())));
        check(BCryptHashData(impl_->hash, const_cast<PUCHAR>(p), n, 0), "BCryptHashData");
        p += n; size -= n;
    }
}
std::array<std::uint8_t, protocol::kSha256DigestBytes> Sha256::finish() {
    if (impl_->finished) throw std::logic_error("SHA-256 already finalized");
    std::array<std::uint8_t, protocol::kSha256DigestBytes> result{};
    check(BCryptFinishHash(impl_->hash, result.data(), static_cast<ULONG>(result.size()), 0), "BCryptFinishHash");
    impl_->finished = true;
    return result;
}
}
