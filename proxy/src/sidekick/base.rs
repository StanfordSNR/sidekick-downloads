use crate::cache::QuackCache;
use crate::stream::{Packet, PacketStream};
use crate::sidekick::ConnectionType;

use sidekick_utils::{BUFFER_SIZE, UDP_PAYLOAD_OFFSET, fmt_hex};
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::buffer::{UdpParser, AddrKey};
use sidekick_utils::packet::{
    DiscoveryPayload, DiscoveryOp, ResetPayload, RESET_FREQ_MS,
};

use std::time::{Instant, Duration};
use log::{trace, debug, info, error};
use quack::{Quack, QuackWrapper};
use crate::cycles::*;

/// The sidekick provides in-network assistance to a single base connection
/// identified by a UDP 4-tuple. It also participates in a separate sidekick
/// connection between the client and proxy, identified by a different UDP
/// 4-tuple.
pub struct Sidekick {
    stream: PacketStream,
    quack_port: u16,
    cache: Option<QuackCache>,
    base_connection_stoc: Option<AddrKey>,
    sidekick_connection: Option<AddrKey>,
    cache_capacity: usize,
    num_retx: usize,
    num_tx: usize,
    last_reset: Instant,
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
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        Self {
            stream,
            quack_port,
            cache: None,
            base_connection_stoc: None,
            sidekick_connection: None,
            cache_capacity,
            num_retx: 0,
            num_tx: 0,
            last_reset: Instant::now(),
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    ///
    /// It is a quACK, so decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, send a Reset packet
    /// back to the client on the sidekick connection.
    fn handle_sidekick_packet_from_client(&mut self, packet: Packet) {
        cycles_start(6);
        let payload = UdpParser::payload(&packet.data, packet.nbytes);
        let quack = QuackWrapper::deserialize(payload);
        let cache = self.cache.as_mut().unwrap();
        cycles_stop(6);
        cycles_start(7);
        match cache.decode(&quack) {
            Ok(result) => {
                cycles_stop(7);
                debug!("quack {} cache_len={} last_index={} missing={:?}, Sidekick: {}",
                    quack.count(), cache.len(),
                    result.last_index, result.missing_indexes,
                    fmt_hex!(self.sidekick_connection.unwrap()));
                cycles_start(8);
                self.num_retx += result.missing_indexes.len();
                for &index in &result.missing_indexes {
                    let retx = cache.get(index).unwrap();
                    cache.add(retx.clone()).unwrap(); // TODO: avoid clone
                    // TODO: roll this in with evict. add() should never exceed
                    // the capacity because we will just remove stuff after
                }
                cycles_stop(8);
                cycles_start(9);
                for &index in &result.missing_indexes {
                    let retx = cache.get(index).unwrap();
                    debug!("retransmit {}/{}", self.num_retx, self.num_tx);
                    self.stream.forward_packet(&retx, retx.nbytes as usize);
                }
                cycles_stop(9);
                cycles_start(10);
                cache.evict();
                cycles_stop(10);
            }
            Err(e) => {
                cycles_stop(7);
                error!("Failed to decode quACK: {:?}", e);
                self.reset_sidekick_connection(packet);
            }
        }
    }

    fn reset_sidekick_connection(&mut self, packet: Packet) {
        if self.last_reset.elapsed() >= Duration::from_millis(RESET_FREQ_MS) {
            let mut buf = [0u8; BUFFER_SIZE];
            match ResetPayload::build_packet(&mut buf, &packet.data) {
                Ok(len) => {
                    info!("Sending reset packet");
                    self.stream.send(&buf, len, packet.iface);
                    self.cache.as_mut().unwrap().reset();
                    self.last_reset = Instant::now();
                }
                Err(e) => error!("Failed to build reset packet: {}", e),
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
        cycles_start(5);
        if let Err(packet) = self.cache.as_mut().unwrap().add(packet) {
            self.reset_sidekick_connection(packet);
        }
        cycles_stop(5);
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
                cycles_start(1);
                self.handle_base_packet_from_client(packet);
                cycles_stop(1);
            }
            ConnectionType::BaseStoc => {
                trace!("Received base packet from server");
                cycles_start(2);
                self.handle_base_packet_from_server(packet);
                cycles_stop(2);
            }
            ConnectionType::Sidekick(_) => {
                trace!("Received sidekick packet from client");
                cycles_start(3);
                self.handle_sidekick_packet_from_client(packet);
                cycles_stop(3);
            }
            ConnectionType::None => {
                trace!("Forwarding packet from unknown four-tuple");
                cycles_start(4);
                self.stream.forward_packet(&packet, packet.nbytes as usize);
                cycles_stop(4);
            }
            _ => {}
        }
    }

    fn handle_discovery_packet(
        &mut self, disc: DiscoveryPayload, addr_key: AddrKey, packet: &Packet,
    ) {
        let base = disc.base_connection_stoc;

        // Check that the discovery packet is well-formed
        assert!(disc.op == DiscoveryOp::Discover);
        assert!(self.base_connection_stoc.is_none() || self.base_connection_stoc == Some(base),
            "expect one base connection");
        assert!(self.sidekick_connection.is_none() || self.sidekick_connection == Some(addr_key),
            "expect one sidekick connection");
        info!("{:?} Received discovery packet from client. Sidekick: {}, Base: {}. Update: {}. riblt={} offset={} threshold={} cache_policy={:?}",
              Instant::now(), fmt_hex!(addr_key), fmt_hex!(base), self.sidekick_connection.is_some(),
              disc.riblt, disc.id_offset, disc.threshold, disc.cache_policy);

        // Initialize the connection for this proxy if not already initialized
        if self.cache.is_none() {
            self.cache = Some(QuackCache::new(
                disc.riblt,
                IdentifierFunc::FixedOffset(UDP_PAYLOAD_OFFSET + disc.id_offset as usize),
                disc.threshold as usize,
                self.cache_capacity,
                disc.cache_policy,
            ));
        }
        self.sidekick_connection = Some(addr_key);
        self.base_connection_stoc = Some(base);

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
                match self.sidekick_connection {
                    Some(stored_key) if stored_key == addr_key => {
                        return ConnectionType::Sidekick(addr_key);
                    }
                    Some(stored_key) => {
                        trace!("Unknown sidekick AddrKey: {} (expected: {})",
                               fmt_hex!(addr_key), fmt_hex!(stored_key));
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
            cycles_start(0);
            self.handle_packet(packet);
            cycles_stop(0);
        }
    }
}