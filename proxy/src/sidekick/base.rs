use crate::cache::QuackCache;
use crate::stream::{Packet, PacketStream};
use crate::sidekick::ConnectionType;

use sidekick_utils::{BUFFER_SIZE, UDP_PAYLOAD_OFFSET, fmt_hex};
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::buffer::{UdpParser, AddrKey};
use sidekick_utils::packet::{
    DiscoveryPayload, DiscoveryOp, ResetPayload, RESET_FREQ_MS,
};

use std::collections::HashMap;
use std::time::{Instant, Duration};
use log::{trace, debug, info, warn, error};
use quack::{Quack, QuackWrapper};
use crate::cycles::*;

struct SidekickConn {
    num_retx: usize,
    num_tx: usize,
    last_reset: Instant,
    cache: QuackCache,
}

impl SidekickConn {
    fn new(cache: QuackCache) -> Self {
        Self {
            num_retx: 0,
            num_tx: 0,
            last_reset: Instant::now(),
            cache,
        }
    }
}

/// The sidekick provides in-network assistance to a single base connection
/// identified by a UDP 4-tuple. It also participates in a separate sidekick
/// connection between the client and proxy, identified by a different UDP
/// 4-tuple.
pub struct Sidekick {
    // Proxy configuration
    stream: PacketStream,
    quack_port: u16,
    cache_capacity: usize,
    cache_capacity_pkts: bool,

    // Per-connection state
    /// Base connection address key to sidekick connection address key.
    /// Base connection is server-to-client (sender-to-receiver).
    /// Sidekick connection is client-to-proxy (receiver-to-proxy).
    base_to_sidekick: HashMap<AddrKey, AddrKey>,
    /// Sidekick connection address key to connection state.
    sidekick_conns: HashMap<AddrKey, SidekickConn>,
}

impl Sidekick {
    /// Initialize a sidekick.
    ///
    /// The base connection 4-tuple is determined by the first UDP packet it
    /// observes on either interface. The sidekick connection 4-tuple is
    /// determined by the first UDP packet it receives destined to its own IP
    /// address and the given quACK port.
    pub fn new(
        client_interface: &str,
        server_interface: &str,
        quack_port: u16,
        cache_capacity: usize,
        cache_capacity_pkts: bool,
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        Self {
            stream,
            quack_port,
            cache_capacity,
            cache_capacity_pkts,
            base_to_sidekick: HashMap::new(),
            sidekick_conns: HashMap::new(),
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    ///
    /// It is a quACK, so decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, send a Reset packet
    /// back to the client on the sidekick connection.
    fn handle_sidekick_packet_from_client(&mut self, packet: Packet, sidekick_conn: &AddrKey) {
        cycles_start(6);
        let payload = UdpParser::payload(&packet.data, packet.nbytes);
        let quack = QuackWrapper::deserialize(payload);
        let conn = self.sidekick_conns.get_mut(sidekick_conn).unwrap();
        cycles_stop(6);
        cycles_start(7);
        match conn.cache.decode(&quack) {
            Ok(result) => {
                cycles_stop(7);
                debug!("quack {} cache_len={} num_symbols={} last_index={} missing={:?}, Sidekick: {}",
                    quack.count(), conn.cache.len(), quack.threshold(),
                    result.last_index, result.missing_indexes, fmt_hex!(sidekick_conn));
                cycles_start(9);
                for (i, &index) in result.missing_indexes.iter().enumerate() {
                    let retx = conn.cache.get(index).unwrap();
                    debug!(
                        "retransmit {} {}/{}",
                        conn.cache.get_id(index).unwrap(),
                        conn.num_retx + i + 1,
                        conn.num_tx,
                    );
                    self.stream.forward_packet(&retx, retx.nbytes as usize);
                }
                cycles_stop(9);
                cycles_start(10);
                conn.cache.evict(true);
                cycles_stop(10);
                conn.num_retx += result.missing_indexes.len();
            }
            Err(e) => {
                cycles_stop(7);
                debug!("quack {} cache_len={} num_symbols={} last_value={}, Sidekick: {}",
                    quack.count(), conn.cache.len(), quack.threshold(),
                    quack.last_value().unwrap(), fmt_hex!(sidekick_conn));
                self.reset_sidekick_connection(packet, sidekick_conn);
                error!("Failed to decode quACK: {:?}", e);
            }
        }
    }

    fn reset_sidekick_connection(&mut self, packet: Packet, sidekick_conn: &AddrKey) -> bool {
        let conn = self.sidekick_conns.get_mut(sidekick_conn).unwrap();
        if conn.last_reset.elapsed() >= Duration::from_millis(RESET_FREQ_MS) {
            let mut buf = [0u8; BUFFER_SIZE];
            match ResetPayload::build_packet(&mut buf, &packet.data) {
                Ok(len) => {
                    info!("Sending reset packet");
                    self.stream.send(&buf, len, packet.iface);
                    conn.cache.reset();
                    conn.last_reset = Instant::now();
                    return true;
                }
                Err(e) => error!("Failed to build reset packet: {}", e),
            }
        }
        false
    }

    /// Handle a packet from the server in the base connection.
    ///
    /// Add it to the cache and forward normally.
    fn handle_base_packet_from_server(&mut self, packet: Packet, sidekick_conn: &AddrKey) {
        self.stream.forward_packet(&packet, packet.nbytes as usize);
        cycles_start(5);
        let conn = self.sidekick_conns.get_mut(sidekick_conn).unwrap();
        conn.num_tx += 1;
        if let Err(packet) = conn.cache.add(packet) {
            if self.reset_sidekick_connection(packet, sidekick_conn) {
                warn!("Reset due to exceeding cache capacity");
            }
        }
        cycles_stop(5);
    }

    /// Filter for packets that belong to the base connection or the sidekick
    /// connection and handle them appropriately. Forward all other packets.
    fn handle_packet(&mut self, packet: Packet) {
        if !UdpParser::is_udp(&packet.data) {
            trace!("Forward non-UDP packet");
            self.stream.forward_packet(&packet, packet.nbytes as usize);
            return;
        }
        match self.connection_type(&packet) {
            ConnectionType::BaseStoc { base_conn, sidekick_conn } => {
                trace!("Received base packet from server");
                cycles_start(2);
                self.handle_base_packet_from_server(packet, &sidekick_conn);
                cycles_stop(2);
            }
            ConnectionType::Sidekick { sidekick_conn } => {
                trace!("Received sidekick packet from client");
                cycles_start(3);
                self.handle_sidekick_packet_from_client(packet, &sidekick_conn);
                cycles_stop(3);
            }
            ConnectionType::None => {
                trace!("Forwarding packet from unknown four-tuple");
                cycles_start(4);
                self.stream.forward_packet(&packet, packet.nbytes as usize);
                cycles_stop(4);
            }
            ConnectionType::Discovery => {}
        }
    }

    fn handle_discovery_packet(
        &mut self, disc: DiscoveryPayload, addr_key: AddrKey, packet: &Packet,
    ) {
        let base = disc.base_connection_stoc;
        assert!(disc.op == DiscoveryOp::Discover);

        // Initialize the connection for this proxy if not already initialized
        let new_conn = !self.sidekick_conns.contains_key(&addr_key);
        if new_conn {
            let cache = QuackCache::new(
                disc.riblt,
                IdentifierFunc::FixedOffset(UDP_PAYLOAD_OFFSET + disc.id_offset as usize),
                disc.threshold as usize,
                self.cache_capacity,
                self.cache_capacity_pkts,
                disc.cache_policy,
            );
            self.base_to_sidekick.insert(base, addr_key);
            self.sidekick_conns.insert(addr_key, SidekickConn::new(cache));
        }
        info!("{:?} Received discovery packet from client. Sidekick: {}, Base: {}. Update: {}. riblt={} offset={} threshold={} cache_policy={:?}",
              Instant::now(), fmt_hex!(addr_key), fmt_hex!(base), !new_conn,
              disc.riblt, disc.id_offset, disc.threshold, disc.cache_policy);

        // Acknowledge the discovery packet
        let mut buf: [u8; BUFFER_SIZE] = [0; BUFFER_SIZE];
        match disc.build_ack_packet(&mut buf, &packet.data) {
            Ok(len) => {
                trace!("Sending ACK packet for discovery {}", fmt_hex!(base));
                self.stream.send(&buf, len, packet.iface);
            }
            Err(e) => error!("Failed to build ack packet: {}", e),
        }
    }

    /// Returns whether this is a base or sidekick connection.
    fn connection_type(&mut self, packet: &Packet) -> ConnectionType {
        let addr_key = UdpParser::parse_addr_key(&packet.data);
        if packet.iface == self.stream.client_iface() {
            // We expect this to be a quACK
            if UdpParser::parse_dst_port(&packet.data) == self.quack_port {
                // Check for discovery packet first
                if let Some(disc) = DiscoveryPayload::from_payload(UdpParser::payload(&packet.data, packet.nbytes)) {
                    self.handle_discovery_packet(disc, addr_key, packet);
                    return ConnectionType::Discovery;
                }
                // Match against sidekick connection
                if self.sidekick_conns.contains_key(&addr_key) {
                    return ConnectionType::Sidekick { sidekick_conn: addr_key };
                }
            }
        } else if packet.iface == self.stream.server_iface() {
            if let Some(sidekick_conn) = self.base_to_sidekick.get(&addr_key) {
                return ConnectionType::BaseStoc {
                    base_conn: addr_key,
                    sidekick_conn: *sidekick_conn,
                };
            }
        }
        ConnectionType::None
    }

    /// Start the sidekick on the packet stream.
    pub async fn start(&mut self) {
        while let Some(packet) = self.stream.receiver.recv().await {
            trace!("Received packet on mpsc: {}", packet.iface);
            cycles_start(0);
            self.handle_packet(packet);
            cycles_stop(0);
        }
    }
}