use crate::cache::QuackCache;
use crate::stream::{Packet, PacketStream};

use sidekick_utils::ID_OFFSET;
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::buffer::{UdpParser, AddrKey};
use sidekick_utils::discovery::DiscoveryPayload;

use log::{trace, debug};
use quack::{PowerSumQuack, PowerSumQuackU32};

/// The sidekick provides in-network assistance to a single base connection
/// identified by a UDP 4-tuple. It also participates in a separate sidekick
/// connection between the client and proxy, identified by a different UDP
/// 4-tuple.
pub struct Sidekick {
    stream: PacketStream,
    cache: QuackCache,
    quack_port: u16,
    base_connection_stoc: Option<AddrKey>,
    sidekick_connection: Option<AddrKey>,
    num_retx: usize,
    num_tx: usize,
}

/// Identifies the connection as base or sidekick
enum ConnectionType {
    /// Base connection from client to server
    BaseCtos,
    /// Base connection from server to client
    BaseStoc,
    /// Sidekick connection
    Sidekick,
    /// Sidekick configuration packet
    Discovery,
    /// Some other connection (forward only)
    None
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
        quack_threshold: usize,
        cache_capacity: usize,
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        let cache = QuackCache::new(
            IdentifierFunc::FixedOffset(ID_OFFSET), // \note should be more cleanly configurable
            quack_threshold,
            cache_capacity
        );
        Self {
            stream,
            cache,
            quack_port,
            base_connection_stoc: None,
            sidekick_connection: None,
            num_retx: 0,
            num_tx: 0,
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    ///
    /// It is a quACK, so decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, reset the quACK by
    /// sending any message back to the client on the sidekick connection.
    fn handle_sidekick_packet_from_client(&mut self, packet: Packet) {
        let payload = UdpParser::payload(&packet.data);
        let quack: PowerSumQuackU32 = bincode::deserialize(payload).unwrap();
        match self.cache.decode(&quack) {
            Ok(result) => {
                debug!("quack {} cache_len={} last_index={} missing={:?}",
                    quack.count(), self.cache.len(),
                    result.last_index, result.missing_indexes);
                for index in result.missing_indexes {
                    let retx = self.cache.get(index).unwrap();
                    self.num_retx += 1;
                    debug!("retransmit {}/{}", self.num_retx, self.num_tx);
                    self.stream.forward_packet(&retx, retx.nbytes as usize);
                    self.cache.add(retx.clone()); // TODO: avoid clone
                }
                self.cache.evict(result.last_index).unwrap();
            }
            Err(_) => {
                // TODO: send any packet to the UDP src of the quacks to reset
                // self.cache.reset();
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
            ConnectionType::Sidekick => {
                trace!("Received sidekick packet from client");
                self.handle_sidekick_packet_from_client(packet);
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
                    info!("Received discovery packet from client. Sidekick: {}, Base: {}. Update: {}.",
                          addr_key.iter()
                                  .map(|b| format!("{:02x}", b))
                                  .collect::<String>(),
                          base.iter()
                              .map(|b| format!("{:02x}", b))
                              .collect::<String>(),
                          self.sidekick_connection.is_some());
                    self.sidekick_connection = Some(addr_key);
                    self.base_connection_stoc = Some(base);
                    return ConnectionType::Discovery;
                }
                // Match against sidekick connection
                match self.sidekick_connection {
                    Some(stored_key) if stored_key == addr_key => {
                        return ConnectionType::Sidekick;
                    }
                    Some(stored_key) => {
                        trace!("Unknown sidekick AddrKey: {} (expected: {})",
                               addr_key.iter()
                                       .map(|b| format!("{:02x}", b))
                                       .collect::<String>(),
                               stored_key.iter()
                                         .map(|b| format!("{:02x}", b))
                                         .collect::<String>());
                        return ConnectionType::None;
                    }
                    None => {
                        trace!("ctos packet received before discovery packet");
                        return ConnectionType::None;
                    }
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
                               flipped_key.iter()
                                          .map(|b| format!("{:02x}", b))
                                          .collect::<String>(),
                               stored_key.iter()
                                         .map(|b| format!("{:02x}", b))
                                         .collect::<String>());
                        return ConnectionType::None;
                    }
                    None => {
                        trace!("Received from ctos stream before discovery (flipped AddrKey: {})",
                               flipped_key.iter()
                                          .map(|b| format!("{:02x}", b))
                                          .collect::<String>());
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
                           addr_key.iter()
                                   .map(|b| format!("{:02x}", b))
                                   .collect::<String>(),
                           stored_key.iter()
                                     .map(|b| format!("{:02x}", b))
                                     .collect::<String>());
                    return ConnectionType::None;
                }
                None => {
                    trace!("Received from stoc stream before discovery (AddrKey: {})",
                           addr_key.iter()
                                   .map(|b| format!("{:02x}", b))
                                   .collect::<String>());
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