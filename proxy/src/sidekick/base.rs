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
use quack::{Quack, QuackWrapper, arithmetic::ModularInteger};
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
    /// The maximum cache capacity before default eviction
    cache_capacity: usize,
    /// Whether to measure the cache capacity in packets, default is bytes
    cache_capacity_pkts: bool,

    // Per-connection state
    /// Base connection address key to sidekick connection address key.
    /// Base connection is server-to-client (sender-to-receiver).
    /// Sidekick connection is client-to-proxy (receiver-to-proxy).
    base_to_sidekick: HashMap<AddrKey, AddrKey>,
    /// Sidekick connection address key to connection state.
    sidekick_conns: HashMap<AddrKey, SidekickConn>,
    /// A buffer to use for constructing packets
    buf: [u8; BUFFER_SIZE],
    /// Pre-alloc'd buffer to store current received quacks
    quack: QuackWrapper,
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
        // Ideally, this is what will be passed into QuackWrapper::deserialize_prealloc.
        // This function expects the vector to be of length:
        // "(buf.len() - 8) / std::mem::size_of::<ModularInteger<u32>>()"
        // Here, `buf` is the received packet. It excludes the first element which
        // is used to identify the type of quack.
        let init_threshold = (BUFFER_SIZE - 1 - 8) /
                                     std::mem::size_of::<ModularInteger<u32>>();
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        Self {
            stream,
            quack_port,
            cache_capacity,
            cache_capacity_pkts,
            base_to_sidekick: HashMap::new(),
            sidekick_conns: HashMap::new(),
            buf: [0u8; BUFFER_SIZE],
            quack: QuackWrapper::new(init_threshold, false),
        }
    }

    // Send a reset message for the sidekick connection if a certain amount of
    // time has elapsed since the last reset message.
    fn reset_sidekick_conn(
        packet: Packet, conn: &mut SidekickConn,
        stream: &mut PacketStream, buf: &mut [u8; BUFFER_SIZE],
    ) -> bool {
        if conn.last_reset.elapsed() >= Duration::from_millis(RESET_FREQ_MS) {
            match ResetPayload::build_packet(buf, &packet.data) {
                Ok(len) => {
                    info!("Sending reset packet");
                    stream.send(buf, len, packet.iface);
                    conn.cache.reset();
                    conn.last_reset = Instant::now();
                    return true;
                }
                Err(e) => error!("Failed to build reset packet: {}", e),
            }
        }
        false
    }

    /// Handle a quACK from the client in the sidekick connection.
    ///
    /// Decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, send a Reset packet
    /// back to the client on the sidekick connection.
    fn handle_quack_from_client(
        &mut self, packet: Packet, sidekick_conn: &AddrKey,
    ) {
        // Validate that the quACK belongs to an initialized sidekick
        let conn = match self.sidekick_conns.get_mut(sidekick_conn) {
            Some(conn) => conn,
            None => {
                warn!("unknown sidekick packet {:?}", fmt_hex!(sidekick_conn));
                return;
            }
        };

        // Decode the quACK
        match conn.cache.decode(&self.quack) {
            Ok(result) => {
                debug!("quack {} cache_len={} num_symbols={} last_index={} missing={:?}, Sidekick: {}",
                    self.quack.count(), conn.cache.len(), self.quack.threshold(),
                    result.last_index, result.missing_indexes, fmt_hex!(sidekick_conn));

                // Retransmit missing packets
                for (i, &index) in result.missing_indexes.iter().enumerate() {
                    let retx = conn.cache.get(index).unwrap();
                    debug!(
                        "retransmit {} {}/{}",
                        conn.cache.get_id(index).unwrap(),
                        conn.num_retx + i + 1,
                        conn.num_tx,
                    );
                    cycles_quack_pause(0);
                    self.stream.forward_packet(&retx, retx.nbytes as usize);
                    cycles_quack_start(0);
                }

                // Update the cache and make retransmission state final
                conn.cache.evict(true);
                conn.num_retx += result.missing_indexes.len();
            }
            Err(e) => {
                debug!("quack {} cache_len={} num_symbols={} last_value={}, Sidekick: {}",
                    self.quack.count(), conn.cache.len(), self.quack.threshold(),
                    self.quack.last_value().unwrap(), fmt_hex!(sidekick_conn));
                cycles_quack_pause(0);
                Self::reset_sidekick_conn(
                    packet, conn, &mut self.stream, &mut self.buf);
                cycles_quack_start(0);
                error!("Failed to decode quACK: {:?}", e);
            }
        }
    }

    /// Initialize a new sidekick connection for the base connection described
    /// in the discovery packet, if it is a new one. Only allows each sidekick
    /// connection 4-tuple to be utilized once (otherwise you need to manually
    /// restart the proxy).
    fn handle_discovery_packet(
        &mut self, disc: DiscoveryPayload, packet: Packet,
        sidekick_conn: &AddrKey,
    ) {
        debug_assert!(disc.op == DiscoveryOp::Discover);
        let base = disc.base_connection_stoc;

        // Initialize the connection for this proxy if not already initialized.
        // Use `entry()` so there is only one hash table lookup.
        let is_update = match self.sidekick_conns.entry(*sidekick_conn) {
            std::collections::hash_map::Entry::Occupied(_) => true,
            std::collections::hash_map::Entry::Vacant(entry) => {
                let cache = QuackCache::new(
                    disc.riblt,
                    IdentifierFunc::FixedOffset(
                        UDP_PAYLOAD_OFFSET + disc.id_offset as usize),
                    disc.threshold as usize,
                    self.cache_capacity,
                    self.cache_capacity_pkts,
                    disc.cache_policy,
                );
                self.base_to_sidekick.insert(base, *sidekick_conn);
                entry.insert(SidekickConn::new(cache));
                false
            }
        };
        info!("{:?} Received discovery packet from client. \
               Sidekick: {}, Base: {}. Update: {}. \
               riblt={} offset={} threshold={} cache_policy={:?}",
              Instant::now(), fmt_hex!(sidekick_conn), fmt_hex!(base), is_update,
              disc.riblt, disc.id_offset, disc.threshold, disc.cache_policy);

        // Acknowledge the discovery packet
        match disc.build_ack_packet(&mut self.buf, &packet.data) {
            Ok(len) => {
                trace!("Sending ACK packet for discovery {}", fmt_hex!(base));
                self.stream.send(&self.buf, len, packet.iface);
            }
            Err(e) => error!("Failed to build ack packet: {}", e),
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    fn handle_sidekick_packet_from_client(
        &mut self, packet: Packet, sidekick_conn: &AddrKey,
    ) {
        let payload = UdpParser::payload(&packet.data, packet.nbytes);
        if let Some(disc) = DiscoveryPayload::from_payload(payload) {
            // Discovery packet
            self.handle_discovery_packet(disc, packet, sidekick_conn);
        } else {
            // QuACKs
            self.quack.deserialize_prealloc(payload);
            self.handle_quack_from_client(packet, sidekick_conn);
            cycles_quack_stop(0);
        }
    }

    /// Handle a packet from the server in the base connection.
    ///
    /// Add it to the cache and forward normally.
    fn handle_base_packet_from_server(
        &mut self, packet: Packet, sidekick_conn: &AddrKey,
    ) {
        if let Some(conn) = self.sidekick_conns.get_mut(sidekick_conn) {
            conn.num_tx += 1;
            let add_result = conn.cache.add(packet);
            if let Err(packet) = add_result {
                cycles_base_pause(0);
                if Self::reset_sidekick_conn(
                    packet, conn, &mut self.stream, &mut self.buf)
                {
                    warn!("Reset due to exceeding cache capacity");
                }
                cycles_base_start(0);
            }
        } else {
            error!("Expected sidekick to exist: {:?}", fmt_hex!(sidekick_conn));
        }
    }

    /// Returns the type of connection the received packet belongs to.
    fn connection_type(&self, packet: &Packet) -> ConnectionType {
        let addr_key = UdpParser::parse_addr_key(&packet.data);
        if packet.iface == self.stream.client_iface() &&
            UdpParser::parse_dst_port(&packet.data) == self.quack_port
        {
            // Assume packets destined to the quACK port (and the proxy IP)
            // are sidekick packets -- either discovery packets or quACKs.
            let ty = ConnectionType::Sidekick { sidekick_conn: addr_key };
            ty
        } else if packet.iface == self.stream.server_iface() {
            // The 4-tuple for this base connection has a sidekick that was
            // previously initialized.
            if let Some(sidekick_conn) = self.base_to_sidekick.get(&addr_key) {
                let ty = ConnectionType::BaseStoc { sidekick_conn: *sidekick_conn };
                ty
            } else {
                ConnectionType::None
            }
        } else {
            ConnectionType::None
        }
    }

    /// Filter for UDP packets that belong to sidekick or base connections and
    /// handle them appropriately. Forward all other packets.
    fn handle_packet(&mut self, packet: Packet) {
        if !UdpParser::is_udp(&packet.data) {
            trace!("Forward non-UDP packet");
            self.stream.forward_packet(&packet, packet.nbytes as usize);
            return;
        }
        cycles_base_start(0);
        cycles_quack_start(0);
        let conn_type = self.connection_type(&packet);
        match conn_type {
            ConnectionType::BaseStoc { sidekick_conn } => {
                trace!("Received base packet from server");
                cycles_base_pause(0);
                self.stream.forward_packet(&packet, packet.nbytes as usize);
                cycles_base_start(0);
                self.handle_base_packet_from_server(packet, &sidekick_conn);
                cycles_base_stop(0);
            }
            ConnectionType::Sidekick { sidekick_conn } => {
                trace!("Received sidekick packet from client");
                self.handle_sidekick_packet_from_client(packet, &sidekick_conn);
            }
            ConnectionType::None => {
                trace!("Forwarding packet from unknown four-tuple");
                self.stream.forward_packet(&packet, packet.nbytes as usize);
            }
        }
    }

    /// Start the sidekick on the packet stream.
    pub async fn start(&mut self) {
        while let Some(packet) = self.stream.receiver.recv().await {
            trace!("Received packet on mpsc: {}", packet.iface);
            self.handle_packet(packet);
        }
    }
}
