use crate::cache::QuackCacheMulticast;
use crate::stream::{Packet, PacketStream};
use crate::sidekick::ConnectionType;

use sidekick_utils::{BUFFER_SIZE, ID_OFFSET, fmt_hex};
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::buffer::{UdpParser, AddrKey};
use sidekick_utils::packet::{
    DiscoveryPayload, DiscoveryOp, ResetPayload, RESET_FREQ_MS,
};

use std::collections::HashMap;
use std::time::{Instant, Duration};
use log::{trace, debug, info, error};
use quack::{PowerSumQuack, PowerSumQuackU32};


/// The sidekick provides in-network assistance to a single multicast base
/// connection identified by a UDP 4-tuple. It also participates in multiple
/// separate sidekick connections between the proxy and different clients, each
/// of which is registered to the multicast address. The sidekick connections
/// are identified by different UDP 4-tuples.
pub struct SidekickMulticast {
    stream: PacketStream,
    cache: QuackCacheMulticast,
    quack_port: u16,
    base_connection_stoc: Option<AddrKey>,
    // Last reset times of each sidekick connection
    sidekick_connections: HashMap<AddrKey, Instant>,
    num_retx: usize,
    num_tx: usize,
}

impl SidekickMulticast {
    /// Initialize a multicast sidekick.
    ///
    /// The base connection 4-tuple is determined by the first discovery
    /// packet it receives. The sidekick connection 4-tuples are determined by
    /// subsequent discovery packets for the same base connection 4-tuple.
    pub fn new(
        client_interface: &str,
        server_interface: &str,
        quack_port: u16,
        quack_threshold: usize,
        cache_capacity: usize,
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        let cache = QuackCacheMulticast::new(
            IdentifierFunc::FixedOffset(ID_OFFSET), // \note should be more cleanly configurable
            quack_threshold,
            cache_capacity
        );
        Self {
            stream,
            cache,
            quack_port,
            base_connection_stoc: None,
            sidekick_connections: HashMap::new(),
            num_retx: 0,
            num_tx: 0,
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    ///
    /// It is a quACK, so decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, send a Reset packet
    /// back to the client on the sidekick connection.
    fn handle_sidekick_packet_from_client(
        &mut self, packet: Packet, sidekick_conn: AddrKey,
    ) {
        let payload = UdpParser::payload(&packet.data);
        let quack: PowerSumQuackU32 = bincode::deserialize(payload).unwrap();
        match self.cache.decode(&quack) {
            Ok(result) => {
                debug!("quack {} cache_len={} last_index={} missing={:?}, Sidekick: {}",
                    quack.count(), self.cache.len(),
                    result.last_index, result.missing_indexes, fmt_hex!(sidekick_conn));
                for index in result.missing_indexes {
                    let retx = self.cache.get(index).unwrap();
                    self.num_retx += 1;
                    debug!("retransmit {}/{}", self.num_retx, self.num_tx);
                    self.stream.forward_packet(&retx, retx.nbytes as usize);
                    self.cache.add(retx.clone()); // TODO: avoid clone
                }
                self.cache.evict(result.last_index).unwrap();
            }
            Err(e) => {
                error!("Failed to decode quACK: {:?}", e);
                if self.sidekick_connections
                    .get(&sidekick_conn)
                    .map(|last_reset| {
                        last_reset.elapsed() >= Duration::from_millis(RESET_FREQ_MS)
                    }).unwrap_or(true)
                {
                    let mut buf = [0u8; BUFFER_SIZE];
                    match ResetPayload::build_packet(&mut buf, &packet.data) {
                        Ok(len) => {
                            info!("Sending reset packet");
                            self.stream.send(&buf, len, packet.iface);
                            self.cache.reset();
                            self.sidekick_connections.insert(sidekick_conn, Instant::now());
                        }
                        Err(e) => error!("Failed to build reset packet: {}", e),
                    }
                }
            }
        }
    }

    /// Handle a packet from the client in the base connection.
    ///
    /// Forward it normally.
    fn handle_base_packet_from_client(&mut self, packet: Packet) {
        self.stream.forward_packet(&packet, packet.nbytes as usize);
    }

    /// Handle a packet from the server in the base connection.
    ///
    /// Add it to the cache and forward normally.
    fn handle_base_packet_from_server(&mut self, packet: Packet) {
        self.stream.forward_packet(&packet, packet.nbytes as usize);
        self.cache.add(packet);
        self.num_tx += 1;
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
            ConnectionType::BaseCtos => {
                trace!("Received base packet from client");
                self.handle_base_packet_from_client(packet);
            }
            ConnectionType::BaseStoc => {
                trace!("Received base packet from server");
                self.handle_base_packet_from_server(packet);
            }
            ConnectionType::Sidekick(conn) => {
                trace!("Received sidekick packet from client");
                self.handle_sidekick_packet_from_client(packet, conn);
            }
            ConnectionType::None => {
                trace!("Forwarding packet from unknown four-tuple");
                self.stream.forward_packet(&packet, packet.nbytes as usize);
            }
            _ => {}
        }
    }

    /// Returns whether this is a base or sidekick connection.
    fn connection_type(&mut self, packet: &Packet) -> ConnectionType {
        let addr_key = UdpParser::parse_addr_key(&packet.data);
        if packet.iface == self.stream.client_iface() {
            // We expect this to be a quACK
            if UdpParser::parse_dst_port(&packet.data) == self.quack_port {
                // Check for discovery packet first
                if let Some(disc) = DiscoveryPayload::from_payload(UdpParser::payload(&packet.data)) {
                    let base = disc.base_connection_stoc;
                    assert!(disc.op == DiscoveryOp::DiscoverMulticast);
                    assert!(self.base_connection_stoc.is_none() ||
                        self.base_connection_stoc == Some(base),
                        "expect one base connection");
                    self.base_connection_stoc = Some(base);
                    let new_conn = self.sidekick_connections.insert(addr_key, Instant::now()).is_none();
                    info!("Received discovery packet from client. Sidekick: {}, Base: {}. New: {}.",
                          fmt_hex!(addr_key), fmt_hex!(base), new_conn);

                    // Acknowledge the discovery packet
                    let mut buf: [u8; BUFFER_SIZE] = [0; BUFFER_SIZE];
                    match disc.build_ack_packet(&mut buf, &packet.data) {
                        Ok(len) => {
                            trace!("Sending ACK packet for discovery {}",
                                   fmt_hex!(self.base_connection_stoc.unwrap()));
                            self.stream.send(&buf, len, packet.iface);
                        }
                        Err(e) => error!("Failed to build ack packet: {}", e),
                    }
                    return ConnectionType::Discovery;
                } else {
                    return ConnectionType::Sidekick(addr_key);
                }
            } else {
                // Convert ctos 4-tuple to stoc 4-tuple
                let flipped_key = UdpParser::flip_addr_key(addr_key);
                match self.base_connection_stoc {
                    Some(stored_key) if stored_key == flipped_key => {
                        return ConnectionType::BaseCtos;
                    },
                    Some(stored_key) => {
                        trace!("Unknown CTOS AddrKey (flipped): {} (expected: {})",
                               fmt_hex!(flipped_key), fmt_hex!(stored_key));
                        return ConnectionType::None;
                    }
                    None => {
                        trace!("Received from ctos stream before discovery (flipped AddrKey: {})",
                               fmt_hex!(flipped_key));
                        return ConnectionType::None;
                    }
                }
            }
        } else if packet.iface == self.stream.server_iface() {
            match self.base_connection_stoc {
                Some(stored_key) if stored_key == addr_key => {
                    return ConnectionType::BaseStoc;
                }
                Some(stored_key) => {
                    trace!("Unknown STOC AddrKey: {} (expected: {})",
                           fmt_hex!(addr_key),
                           fmt_hex!(stored_key));
                    return ConnectionType::None;
                }
                None => {
                    trace!("Received from stoc stream before discovery (AddrKey: {})",
                           fmt_hex!(addr_key));
                    return ConnectionType::None;
                }
            }
        }
        ConnectionType::None
    }

    /// Start the sidekick on the packet stream.
    pub async fn start(&mut self) {
        while let Some(packet) = self.stream.receiver.recv().await {
            trace!("Received packet on mpsc: {}", packet.iface);
            self.handle_packet(packet);
        }
    }
}
