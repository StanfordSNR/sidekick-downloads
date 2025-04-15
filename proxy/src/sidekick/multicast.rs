use crate::cache::QuackCacheMulticast;
use crate::stream::{Packet, PacketStream};
use crate::sidekick::ConnectionType;

use sidekick_utils::{BUFFER_SIZE, UDP_PAYLOAD_OFFSET, fmt_hex};
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::buffer::{UdpParser, AddrKey};
use sidekick_utils::packet::{
    RetransmitPayload, DiscoveryPayload, ResetPayload,
    DiscoveryOp, RESET_FREQ_MS,
};

use std::collections::HashMap;
use std::time::{Instant, Duration};
use log::{trace, debug, info, error};
use quack::{Quack, QuackWrapper};

struct BaseConn {
    // server-to-client
    addr: AddrKey,
    cache: QuackCacheMulticast,
    num_tx: usize,
}

impl BaseConn {
    fn new(addr: &AddrKey, cache: QuackCacheMulticast) -> Self {
        Self {
            addr: *addr,
            cache,
            num_tx: 0,
        }
    }
}

struct SidekickConn {
    last_reset: Instant,
    num_retx: usize,
}

impl SidekickConn {
    fn new() -> Self {
        Self {
            last_reset: Instant::now(),
            num_retx: 0,
        }
    }
}

/// The sidekick provides in-network assistance to a single multicast base
/// connection identified by a UDP 4-tuple. It also participates in multiple
/// separate sidekick connections between the proxy and different clients, each
/// of which is registered to the multicast address. The sidekick connections
/// are identified by different UDP 4-tuples.
pub struct SidekickMulticast {
    stream: PacketStream,
    quack_port: u16,
    cache_capacity: usize,

    /// Multicast base connection state
    base_conn: Option<BaseConn>,
    /// Map from sidekick address key to the sidekick connection state
    sidekick_conns: HashMap<AddrKey, SidekickConn>,

    /// A buffer to use for constructing packets
    buf: [u8; BUFFER_SIZE],
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
        cache_capacity: usize,
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        Self {
            stream,
            quack_port,
            cache_capacity,
            base_conn: None,
            sidekick_conns: HashMap::new(),
            buf: [0; BUFFER_SIZE],
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    ///
    /// It is a quACK, so decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, send a Reset packet
    /// back to the client on the sidekick connection.
    fn handle_quack_from_client(
        &mut self, quack: QuackWrapper, packet: Packet, sidekick_conn: &AddrKey,
    ) {
        let base = self.base_conn.as_mut().unwrap();
        let conn = self.sidekick_conns.get_mut(sidekick_conn).unwrap();
        match base.cache.decode(&quack, sidekick_conn) {
            Ok(result) => {
                debug!("quack {} cache_len={} num_symbols={} {:?} last_index={} missing={:?}, Sidekick: {}",
                    quack.count(), base.cache.view().len(), quack.threshold(),
                    base.cache.view_ids(), result.last_index,
                    result.missing_indexes, fmt_hex!(sidekick_conn));

                // Retransmit missing packets
                for (i, &index) in result.missing_indexes.iter().enumerate() {
                    let retx = base.cache.get(index).unwrap();
                    debug!(
                        "retransmit {}/{}",
                        conn.num_retx + i + 1,
                        base.num_tx,
                    );
                    let inner = UdpParser::payload(&retx.data, retx.nbytes);
                    let outer = RetransmitPayload::new(inner);
                    match outer.build_packet(&mut self.buf, &packet.data) {
                        Ok(len) => {
                            debug!(
                                "retransmit original payload {} {}",
                                retx.nbytes, len,
                            );
                            self.stream.send(&self.buf, len, packet.iface);
                        }
                        Err(e) => error!("Failed to build retransmit packet: {}", e),
                    }
                }

                // Update the cache and make retransmission state final
                let num_evicted = base.cache.evict();
                trace!("evicting {}", num_evicted);
                conn.num_retx += result.missing_indexes.len();
            }
            Err(e) => {
                debug!("quack {} cache_len={} num_symbols={} last_value={}, Sidekick: {}",
                    quack.count(), base.cache.len(), quack.threshold(),
                    quack.last_value().unwrap(), fmt_hex!(sidekick_conn));
                if conn.last_reset.elapsed() >= Duration::from_millis(RESET_FREQ_MS) {
                    match ResetPayload::build_packet(&mut self.buf, &packet.data) {
                        Ok(len) => {
                            info!("Sending reset packet");
                            self.stream.send(&self.buf, len, packet.iface);
                            base.cache.reset(sidekick_conn);
                            conn.last_reset = Instant::now();
                        }
                        Err(e) => error!("Failed to build reset packet: {}", e),
                    }
                }
                error!("Failed to decode quACK: {:?}", e);
            }
        }
    }

    fn handle_discovery_packet(
        &mut self, disc: DiscoveryPayload, addr_key: AddrKey, packet: &Packet,
    ) {
        let base = disc.base_connection_stoc;
        assert!(disc.op == DiscoveryOp::DiscoverMulticast);

        // Initialize the base connection for this proxy if not already
        if self.base_conn.is_none() {
            let cache = QuackCacheMulticast::new(
                IdentifierFunc::FixedOffset(UDP_PAYLOAD_OFFSET + disc.id_offset as usize),
                self.cache_capacity,
            );
            self.base_conn = Some(BaseConn::new(&base, cache));
        }
        assert_eq!(self.base_conn.as_ref().unwrap().addr, base, "one base connection");

        // Initialize the sidekick connection for this discovery packet
        let conn = SidekickConn::new();
        let is_new = self.sidekick_conns.insert(addr_key, conn).is_none();
        info!("Received discovery packet from client. Sidekick: {}, Base: {}. New: {}.",
              fmt_hex!(addr_key), fmt_hex!(base), is_new);

        // Acknowledge the discovery packet
        let threshold = disc.threshold;
        let riblt = disc.riblt;
        match disc.build_ack_packet(&mut self.buf, &packet.data) {
            Ok(len) => {
                trace!("Sending ACK packet for discovery {:?}", base);
                self.stream.send(&self.buf, len, packet.iface);
                self.base_conn.as_mut().unwrap().cache.init_conn(
                    &addr_key, threshold as usize, riblt,
                );
            }
            Err(e) => error!("Failed to build ack packet: {}", e),
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    fn handle_sidekick_packet_from_client(
        &mut self, packet: Packet, sidekick_conn: &AddrKey,
    ) {
        // Check for discovery packet first
        let payload = UdpParser::payload(&packet.data, packet.nbytes);
        if let Some(disc) = DiscoveryPayload::from_payload(payload) {
            self.handle_discovery_packet(disc, *sidekick_conn, &packet);
        } else {
            let quack = QuackWrapper::deserialize(payload);
            self.handle_quack_from_client(quack, packet, sidekick_conn);
        }
    }

    /// Handle a packet from the server in the base connection.
    ///
    /// Add it to the cache and forward normally.
    fn handle_base_packet_from_server(&mut self, packet: Packet) {
        let base = self.base_conn.as_mut().unwrap();
        base.cache.add(packet);
        base.num_tx += 1;
    }

    /// Returns whether this is a base or sidekick connection.
    fn connection_type(&mut self, packet: &Packet) -> ConnectionType {
        let addr_key = UdpParser::parse_addr_key(&packet.data);
        if packet.iface == self.stream.client_iface() &&
            UdpParser::parse_dst_port(&packet.data) == self.quack_port
        {
            ConnectionType::Sidekick { sidekick_conn: addr_key }
        } else if packet.iface == self.stream.server_iface() &&
            self.base_conn.as_ref().map(|base| base.addr == addr_key).unwrap_or(false)
        {
            // addr_key is actually the base_conn
            ConnectionType::BaseStoc { sidekick_conn: addr_key }
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
        match self.connection_type(&packet) {
            ConnectionType::BaseStoc { .. } => {
                trace!("Received base packet from server");
                self.stream.forward_packet(&packet, packet.nbytes as usize);
                self.handle_base_packet_from_server(packet);
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
