use crate::cache::QuackCache;
use crate::stream::{Packet, PacketStream};
use crate::identifier::IdentifierFunc;
use log::trace;

/// The sidekick provides in-network assistance to a single base connection
/// identified by a UDP 4-tuple. It also participates in a separate sidekick
/// connection between the client and proxy, identified by a different UDP
/// 4-tuple.
pub struct Sidekick {
    stream: PacketStream,
    cache: QuackCache,
    quack_port: u16,
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
    ) -> Self {
        let stream = PacketStream::new(client_interface.into(), server_interface.into());
        let cache = QuackCache::new(
            IdentifierFunc::FirstByte,
            quack_threshold
        );
        Self {
            stream,
            cache,
            quack_port
        }
    }

    /// Handle a packet from the client in the sidekick connection.
    ///
    /// It is a quACK, so decode the quACK. The most basic functionality is
    /// then to retransmit missing packets and delete acknowledged packets
    /// from the cache. If the quACK can't be decoded, reset the quACK by
    /// sending any message back to the client on the sidekick connection.
    fn handle_sidekick_packet_from_client(&mut self, packet: Packet) {
        unimplemented!()
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
    }

    /// Filter for packets that belong to the base connection or the sidekick
    /// connection and handle them appropriately. Forward all other packets.
    fn handle_packet(&mut self, packet: Packet) {
        unimplemented!()
    }

    /// Start the sidekick on the packet stream.
    pub async fn start(&mut self) {
        while let Some(packet) = self.stream.receiver.recv().await {
            trace!("Received packet on mpsc: {}", packet.iface);
            self.handle_packet(packet);
        }
    }
}