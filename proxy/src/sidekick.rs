use crate::cache::QuackCache;
use crate::stream::{Packet, PacketStream};

use sidekick_utils::{BUFFER_SIZE, ID_OFFSET};
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::buffer::{UdpParser, AddrKey};
use sidekick_utils::discovery::{DiscoveryPayload, DiscoveryOp};

use log::{trace, debug, info, error};
use hashbrown::HashMap;

use quack::{PowerSumQuack, PowerSumQuackU32};

/// A table tracking all sidekick connections.
/// As quacks are not marked with a specific base connection,
/// each base connection must have a distinct sidekick connection.
pub struct SidekickTable {
    /// A packet stream between the socket that is expected
    /// to receive packets from the client (including quACKs)
    /// and the socket that is expected to receive from the server.
    stream: PacketStream,
    /// Base connection AddrKey -> sidekick struct
    /// AddrKey should be calculated in server-to-client (stoc) direction.
    base_stoc: HashMap<AddrKey, Sidekick>,
    /// Sidekick connection AddrKey -> base connection AddrKey
    sk_to_base: HashMap<AddrKey, AddrKey>,
    /// UDP port quACKs are expected on
    quack_port: u16,
    /// Threshold number of missing packets in each quACK.
    quack_threshold: usize,
    /// Capacity of the quACK cache.
    cache_capacity: usize,
}

impl SidekickTable {
    /// Create a new sidekick table.
    pub fn new(
        client_interface: &str,
        server_interface: &str,
        quack_port: u16,
        quack_threshold: usize,
        cache_capacity: usize
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        Self {
            stream,
            base_stoc: HashMap::new(),
            sk_to_base: HashMap::new(),
            quack_port,
            quack_threshold,
            cache_capacity,
        }
    }

    /// Start the sidekick handler on the packet stream.
    pub async fn start(&mut self) {
        while let Some(packet) = self.stream.receiver.recv().await {
            trace!("Received packet on mpsc: {}", packet.iface);
            self.handle_packet(packet);
        }
    }

    /// Handle an incoming packet
    ///
    /// Forward all non-UDP packets.
    /// If the packet's AddrKey is in the sidekick table, process it.
    /// If not, check if it's a discovery packet; if so, create a new sidekick.
    /// If neither, forward the packet.
    fn handle_packet(&mut self, packet: Packet) {
        let mut sk = None;
        let conn_type = self.connection_type(&packet);
        match conn_type {
            ConnectionType::BaseCtos => {
                sk = self.base_stoc.get_mut(&UdpParser::flip_addr_key(UdpParser::parse_addr_key(&packet.data)));
            },
            ConnectionType::BaseStoc => {
                sk = self.base_stoc.get_mut(&UdpParser::parse_addr_key(&packet.data));
            },
            ConnectionType::Sidekick => {
                let base_key = self.sk_to_base.get(&UdpParser::parse_addr_key(&packet.data));
                if let Some(k) = base_key {
                    sk = self.base_stoc.get_mut(k);
                }
            },
            ConnectionType::Discovery => {
                self.handle_discovery(packet);
                return; // don't forward
            },
        }
        match sk {
            Some(sidekick) => {
                sidekick.handle_packet(packet, &self.stream, conn_type);
            },
            None => {
                trace!("Forwarding packet from unknown four-tuple");
                self.stream.forward_packet(&packet, packet.nbytes as usize);
            }
        }
    }

    /// Returns whether this is a base or sidekick connection.
    fn connection_type(&self, packet: &Packet) -> ConnectionType {
        if packet.iface == self.stream.client_iface() {
            // We expect this to be a quACK
            if UdpParser::parse_dst_port(&packet.data) == self.quack_port {
                // Check for discovery packet first; ACK it if so.
                // This indicates either a new connection or that a previous DiscoveryAck got lost.
                if let Some(_) = DiscoveryPayload::from_payload(UdpParser::payload(&packet.data)) {
                    return ConnectionType::Discovery;
                } else {
                    return ConnectionType::Sidekick;
                }
            } else {
                return ConnectionType::BaseCtos;
            }
        } else if packet.iface == self.stream.server_iface() {
            return ConnectionType::BaseStoc;
        }
        panic!("Packet received on unknown interface: {}", packet.iface);
    }

    /// ACK the discovery.
    /// If the Sidekick does not exist in the table, insert it.
    /// Method assumes that the packet is known to be a Discovery packet.
    fn handle_discovery(&mut self, packet: Packet) {
        let disc = DiscoveryPayload::from_payload(UdpParser::payload(&packet.data)).unwrap();
        if disc.op != DiscoveryOp::Discover { return; }
        let addr_key = UdpParser::parse_addr_key(&packet.data);
        let base = disc.base_connection_stoc;
        info!("Received discovery packet from client. Sidekick: {}, Base: {}",
              addr_key.iter()
                      .map(|b| format!("{:02x}", b))
                      .collect::<String>(),
              base.iter()
                  .map(|b| format!("{:02x}", b))
                  .collect::<String>());
        // Send ACK
        let mut buf: [u8; BUFFER_SIZE] = [0; BUFFER_SIZE];
        match disc.build_ack_packet(&mut buf, &packet.data) {
            Ok(len) => {
                trace!("Sending ACK packet for discovery packet");
                self.stream.send(&buf, len, packet.iface);
            }
            Err(e) => error!("Failed to build ack packet: {}", e),
        }
        // Check for an update (new sidekick connection for base connection)
        if self.sk_to_base.get(&addr_key).is_none() || self.base_stoc.get(&base).is_none() {
            self.insert_sidekick(addr_key, base);
        }
    }

    /// Add a new sidekick to the table.
    /// Sidekick connection identifier -> base connection identifier
    /// Base connection identifier -> sidekick struct
    fn insert_sidekick(&mut self, sk: AddrKey, base: AddrKey) {
        info!("Inserting new sidekick connection: {} -> {}",
              sk.iter()
                .map(|b| format!("{:02x}", b))
                .collect::<String>(),
              base.iter()
                  .map(|b| format!("{:02x}", b))
                  .collect::<String>());
        self.sk_to_base.insert(sk, base);
        self.base_stoc.insert(base, Sidekick::new(
            self.quack_threshold,
            self.cache_capacity,
        ));
    }
}

/// The sidekick provides in-network assistance to a single base connection
/// identified by a UDP 4-tuple. It also participates in a separate sidekick
/// connection between the client and proxy, identified by a different UDP
/// 4-tuple.
pub struct Sidekick {
    cache: QuackCache,
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
}

impl Sidekick {
    /// Initialize a sidekick.
    ///
    /// The base connection 4-tuple is determined by the first UDP packet it
    /// observes on either interface. The sidekick connection 4-tuple is
    /// determined by the first UDP packet it receives destined to its own IP
    /// address and the given quACK port.
    pub fn new(
        quack_threshold: usize,
        cache_capacity: usize,
    ) -> Self {
        let cache = QuackCache::new(
            IdentifierFunc::FixedOffset(ID_OFFSET), // \note should be more cleanly configurable
            quack_threshold,
            cache_capacity
        );
        Self {
            cache,
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
    fn handle_sidekick_packet_from_client(&mut self, packet: Packet, stream: &PacketStream) {
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
                    stream.forward_packet(&retx, retx.nbytes as usize);
                    self.cache.add(retx.clone()); // TODO: avoid clone
                }
                self.cache.evict(result.last_index).unwrap();
            }
            Err(e) => {
                error!("Failed to decode quACK: {:?}", e);
                // TODO: send any packet to the UDP src of the quacks to reset
                // self.cache.reset();
            }
        }
    }

    /// Handle a packet from the client in the base connection.
    ///
    /// Forward it normally.
    fn handle_base_packet_from_client(&mut self, packet: Packet, stream: &PacketStream) {
        stream.forward_packet(&packet, packet.nbytes as usize);
    }

    /// Handle a packet from the server in the base connection.
    ///
    /// Add it to the cache and forward normally.
    fn handle_base_packet_from_server(&mut self, packet: Packet, stream: &PacketStream) {
        stream.forward_packet(&packet, packet.nbytes as usize);
        self.cache.add(packet);
        self.num_tx += 1;
    }

    /// Filter for packets that belong to the base connection or the sidekick
    /// connection and handle them appropriately. Forward all other packets.
    fn handle_packet(&mut self, packet: Packet, stream: &PacketStream,
                     connection_type: ConnectionType) {
        match connection_type {
            ConnectionType::BaseCtos => {
                trace!("Received base packet from client");
                self.handle_base_packet_from_client(packet, stream);
            }
            ConnectionType::BaseStoc => {
                trace!("Received base packet from server");
                self.handle_base_packet_from_server(packet, stream);
            }
            ConnectionType::Sidekick => {
                trace!("Received sidekick packet from client");
                self.handle_sidekick_packet_from_client(packet, stream);
            }
            ConnectionType::Discovery => {
                panic!("Discovery packet should have been handled by SidekickTable");
            }
        }
    }

}