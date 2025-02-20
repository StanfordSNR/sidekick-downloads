#ifndef SIDEKICK_UTILS_H
#define SIDEKICK_UTILS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

extern const size_t ID_OFFSET;
extern const size_t UDP_PAYLOAD_OFFSET;
extern const uint64_t RESET_FREQ_MS;
extern const uint64_t DISCOVERY_FREQ_MS;
extern const size_t NUM_DISCOVERY_PKTS;

void sidekick_init_logging();
uint32_t sidekick_fixed_offset_to_id(const uint8_t* bytes, size_t packet_length, size_t offset);

#ifdef __cplusplus
}
#endif

#endif // SIDEKICK_UTILS_H