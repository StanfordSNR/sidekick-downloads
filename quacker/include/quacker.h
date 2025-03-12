#ifndef QUACKER_H
#define QUACKER_H

#define ADDR_KEY_LEN 12

#ifdef __cplusplus
extern "C" {
#endif

typedef struct UdpQuacker UdpQuacker;

UdpQuacker* udp_quacker_new(size_t threshold, uint32_t freq_pkts, uint64_t freq_ms, const char* addr, int riblt);
void udp_quacker_handle_sidekick_payload(UdpQuacker* quacker, const uint8_t* udp_payload, size_t len);
void udp_quacker_send_discovery(UdpQuacker* quacker, const uint8_t (*base)[ADDR_KEY_LEN], size_t n);
int udp_quacker_base_stoc_is_none(const UdpQuacker* quacker);
int udp_quacker_awaiting_disc_ack(const UdpQuacker* quacker);
struct sockaddr_in udp_quacker_src_addr(const UdpQuacker* quacker);
struct sockaddr_in udp_quacker_dst_addr(const UdpQuacker* quacker);
uint32_t udp_quacker_freq_pkts(const UdpQuacker* quacker);
uint64_t udp_quacker_freq_ms(const UdpQuacker* quacker);
void udp_quacker_reset(UdpQuacker* quacker);
int udp_quacker_insert(UdpQuacker* quacker, uint64_t time_ms, uint32_t id);
int udp_quacker_update_time(UdpQuacker* quacker, uint64_t time_ms);
void udp_quacker_send_quack(UdpQuacker* quacker, uint64_t time_ms);
void udp_quacker_send_quack_with_hint(UdpQuacker* quacker, uint64_t time_ms, size_t num_symbols);
void udp_quacker_free(UdpQuacker* quacker);

#ifdef __cplusplus
}
#endif

#endif // QUACKER_H