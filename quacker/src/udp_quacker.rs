use std::net::{SocketAddr, UdpSocket};
use std::sync::Arc;
use bincode;
use log::{debug, info, error, warn};
use socket2::{Socket, Domain, Type, SockAddr};

use quack::{Quack, QuackWrapper};
use crate::{Quacker, BaseQuacker};

use sidekick_utils::{fmt_hex, BUFFER_SIZE, ID_OFFSET, UDP_PAYLOAD_OFFSET};
use sidekick_utils::buffer::AddrKey;
use sidekick_utils::packet::{
    ResetPayload, DiscoveryPayload, RetransmitPayload, DiscoveryOp,
};


#[derive(Clone)]
pub struct UdpQuacker {
    quacker: BaseQuacker,
    src_sock: Arc<UdpSocket>,
    dst_addr: SocketAddr,
    buf: [u8; BUFFER_SIZE],
    pub base_stoc: Option<AddrKey>, // base conn 4-tuple
    pub awaiting_disc_ack: bool, // requested discovery, awaiting ack
}

impl UdpQuacker {
    pub fn new(
        threshold: usize, freq_pkts: u32, freq_ms: u64, addr: SocketAddr,
        riblt: bool,
    ) -> Self {
        let socket = Socket::new(Domain::IPV4, Type::DGRAM, None).unwrap();
        socket.set_reuse_address(true).unwrap();
        socket.bind(&SockAddr::from(
            "0.0.0.0:0".parse::<SocketAddr>().unwrap())).unwrap();
        Self {
            quacker: BaseQuacker::new(riblt, threshold, freq_pkts, freq_ms),
            src_sock: Arc::new(socket.into()),
            dst_addr: addr,
            buf: [0u8; BUFFER_SIZE],
            base_stoc: None,
            awaiting_disc_ack: false,
        }
    }

    /// Handle an incoming sidekick packet from the proxy.
    pub fn handle_sidekick_payload(&mut self, udp_payload: &[u8]) -> Option<Vec<u8>> {
        if let Some(disc) = DiscoveryPayload::from_payload(udp_payload) {
            self.handle_discover_ack(disc);
        } else if let Some(_) = ResetPayload::from_payload(udp_payload) {
            info!("Received Reset, count={}", self.quacker.get_quack().count());
            self.reset();
        } else if let Some(retx) = RetransmitPayload::from_payload(udp_payload) {
            debug!("Received Retransmit");
            return Some(retx.data);
        } else {
            warn!("Received unknown packet from proxy {} bytes", udp_payload.len());
        }
        None
    }

    /// Handle discovery packets from the proxy.
    /// Assumes that this packet is known to be a UDP packet from the proxy
    /// by source port and IP address.
    fn handle_discover_ack(&mut self, disc: DiscoveryPayload) {
        if disc.op == DiscoveryOp::DiscoverAck {
            if Some(disc.base_connection_stoc) == self.base_stoc {
                // Start aggregating quacks only after proxy is ready.
                // May receive dup discovery ACKs; only initialize (reset)
                // on first one.
                if self.awaiting_disc_ack {
                    self.reset();
                    self.awaiting_disc_ack = false;
                    info!("Received DiscoverACK from proxy");
                }
            } else if self.base_stoc.is_some() {
                error!("Received DiscoverACK from proxy for old data: {} (expected: {})",
                        fmt_hex!(disc.base_connection_stoc),
                        fmt_hex!(self.base_stoc.unwrap()));
            } else {
                panic!("Received DiscoverACK from proxy before sending discovery");
            }
        } else {
            warn!("Received packet from proxy with op {:?}", disc.op);
        }
    }

    /// Send discovery through `socket` to `addr`
    /// `base` is assumed to be the AddrKey of the base connection
    /// `socket` and `addr` are assumed to be the sidekick connection.
    ///
    /// Note: this will send `n` identical discovery packets. For n > 1, this increases
    /// the chance that a discovery reaches the proxy in the presence of random loss
    /// (duplicate discovery packets are no-ops).
    pub fn send_discovery(&mut self, base: AddrKey, n: usize) {
        self.send_discovery_base(base, n, false);
    }

    pub fn send_discovery_multicast(&mut self, base: AddrKey, n: usize) {
        self.send_discovery_base(base, n, true);
    }

    fn send_discovery_base(
    &mut self, base: AddrKey, n: usize, multicast: bool,
    ) {
        self.base_stoc = Some(base);
        self.awaiting_disc_ack = true;
        let op = if multicast {
            DiscoveryOp::DiscoverMulticast
        } else {
            DiscoveryOp::Discover
        };
        let id_offset: u16 = (ID_OFFSET - UDP_PAYLOAD_OFFSET).try_into().unwrap();
        let threshold: u8 = self.quacker.threshold().try_into().unwrap();
        let riblt = self.quacker.riblt();
        let bytes = bincode::serialize(
            &DiscoveryPayload::new(base, op, id_offset, threshold, riblt)
        ).unwrap();
        for i in 0..n {
            if self.src_sock.send_to(&bytes, self.dst_addr).is_err() {
                error!("Failed to send {}th discovery packet", i);
                return;
            } else {
                info!("Sent discovery for sidekick base connection {}",
                      fmt_hex!(base));
            }
        }
    }

    /// The local UDP socket.
    pub fn src_sock(&self) -> Arc<UdpSocket> {
        self.src_sock.clone()
    }

    /// The socket address on which we expect to receive resets.
    ///
    /// The application is responsible for identifying reset packets in order
    /// to serialize them with base connection packets.
    pub fn src_addr(&self) -> SocketAddr {
        self.src_sock.local_addr().unwrap()
    }

    /// The socket address to which we send quACKs on the sidekick connection.
    pub fn dst_addr(&self) -> SocketAddr {
        self.dst_addr.clone()
    }
}

impl Quacker for UdpQuacker {
    fn freq_pkts(&self) -> u32 {
        self.quacker.freq_pkts()
    }

    fn freq_ms(&self) -> u64 {
        self.quacker.freq_ms()
    }

    fn get_quack(&self) -> &QuackWrapper {
        self.quacker.get_quack()
    }

    fn reset(&mut self) {
        self.quacker.reset();
    }

    fn insert(&mut self, time_ms: u64, id: u32) -> bool {
        if self.base_stoc.is_some() && !self.awaiting_disc_ack {
            let should_quack = self.quacker.insert(time_ms, id);
            if should_quack {
                self.send_quack(time_ms);
            }
            should_quack
        } else {
            false
        }
    }

    fn update_time(&mut self, time_ms: u64) -> bool {
        let should_quack = self.quacker.update_time(time_ms);
        if should_quack {
            self.send_quack(time_ms);
        }
        should_quack
    }

    fn send_quack(&mut self, time_ms: u64) {
        self.quacker.send_quack(time_ms);
        let mut buf = self.buf;
        let quack = self.get_quack();
        debug!("quack {}", quack.count());
        let len = quack.serialize(&mut buf[..]);
        self.src_sock.send_to(&buf[..len], self.dst_addr).unwrap();
    }
}

impl UdpQuacker {
    pub fn send_quack_with_hint(&mut self, time_ms: u64, num_symbols: usize) {
        self.quacker.send_quack(time_ms);
        let mut buf = self.buf;
        let quack = self.get_quack();
        debug!("quack {}", quack.count());
        let len = quack.serialize_with_hint(&mut buf[..], num_symbols);
        self.src_sock.send_to(&buf[..len], self.dst_addr).unwrap();
    }
}
