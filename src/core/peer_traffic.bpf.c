// Passive AF_PACKET/SOCK_DGRAM observer: return 0 discards only our socket's
// copy. No payload reaches userspace; no TC/XDP policy or qdisc is changed.
#include <uapi/linux/bpf.h>
#include <uapi/linux/ip.h>
#include <uapi/linux/ipv6.h>
#include <bcc/proto.h>

struct address_t { u8 bytes[16]; u32 family; };
struct peer_t { struct address_t address; u32 outgoing; };
BPF_HASH(local_addresses, struct address_t, u8, 64);
BPF_HASH(peer_bytes, struct peer_t, u64, 4096);
BPF_ARRAY(overflows, u64, 1);

int observe(struct __sk_buff *skb) {
    // PACKET_HOST / PACKET_OUTGOING only, no broadcasts or promiscuous traffic.
    if (skb->pkt_type != 0 && skb->pkt_type != 4) return 0;
    struct address_t src = {}, dst = {};
    u32 offset = 0;
    u16 protocol = bpf_ntohs(skb->protocol);
    // Cooked sockets start at the network header, also on tun/WireGuard.
    // If a VLAN header remains inline, peel at most two tags.
    #pragma unroll
    for (int i = 0; i < 2; i++) {
        if (protocol == 0x8100 || protocol == 0x88a8) {
            u16 next = 0;
            if (bpf_skb_load_bytes(skb, offset + 2, &next, 2)) return 0;
            protocol = bpf_ntohs(next);
            offset += 4;
        }
    }
    u64 amount = 0;
    if (protocol == 0x0800) {
        struct iphdr ip = {};
        if (bpf_skb_load_bytes(skb, offset, &ip, sizeof(ip))) return 0;
        if (ip.version != 4 || ip.ihl < 5) return 0;
        amount = bpf_ntohs(ip.tot_len);
        // BIG TCP can exceed the 16-bit IP length before segmentation.
        if (skb->len - offset > 65535) amount = skb->len - offset;
        if (amount < ip.ihl * 4 || amount > skb->len - offset) return 0;
        src.family = dst.family = 4;
        __builtin_memcpy(src.bytes, &ip.saddr, 4);
        __builtin_memcpy(dst.bytes, &ip.daddr, 4);
    } else if (protocol == 0x86dd) {
        struct ipv6hdr ip = {};
        if (bpf_skb_load_bytes(skb, offset, &ip, sizeof(ip))) return 0;
        if (ip.version != 6) return 0;
        amount = 40 + bpf_ntohs(ip.payload_len);
        if (ip.payload_len == 0) amount = skb->len - offset;
        if (amount < 40 || amount > skb->len - offset) return 0;
        src.family = dst.family = 6;
        __builtin_memcpy(src.bytes, &ip.saddr, 16);
        __builtin_memcpy(dst.bytes, &ip.daddr, 16);
    } else return 0;

    struct peer_t key = {};
    key.outgoing = skb->pkt_type == 4;
    if (key.outgoing) {
        if (!local_addresses.lookup(&src)) return 0;
        key.address = dst;
    } else {
        if (!local_addresses.lookup(&dst)) return 0;
        key.address = src;
    }
    if (local_addresses.lookup(&key.address)) return 0;
    u64 zero = 0;
    u64 *count = peer_bytes.lookup_or_try_init(&key, &zero);
    if (count) __sync_fetch_and_add(count, amount);
    else {
        u32 index = 0;
        u64 *lost = overflows.lookup(&index);
        if (lost) __sync_fetch_and_add(lost, 1);
    }
    return 0;
}
