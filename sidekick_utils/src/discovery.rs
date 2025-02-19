//! Structures for a very basic Sidekick discovery protocol.
//!
//! Client (receiver) opens a sidekick connection and uses it to send the
//! proxy a Discovery packet with DiscoveryOp = 0 (Discover).
//! The discovery packet contains the four-tuple of the base connection.
//!
//! The base connection four-tuple should be from the perspective of
//! the server (sender). I.e., the client should "flip" the four-tuple
//! of the base connection it is requesting assistance on, such that
//! its source IP/port become the destination IP/port and vice verse.
//!
//! The proxy responds with a Discovery packet with DiscoveryOp = 1
//! (DiscoverAck). The client should continue retransmitting Discovery
//! packets at a regular interval until the DiscoverAck is received.
//!
//! The client can update its base or sidekick connection at any time
//! by sending a new Discovery packet with DiscoveryOp = 0. This will
//! reset state on the proxy.
//!
//! The client can tear down a sidekick connection by sending a
//! Discovery packet with DiscoveryOp = 2 (Teardown). The proxy will
//! reply with a Discovery packet with DiscoveryOp = 3 (TeardownAck),
//! and the client should continue retransmitting the teardown until
//! the TeardownAck is received. The Teardown must be transmitted on the
//! sidekick connection (four-tuple) and must contain the base connection
//! four-tuple.
//!
//! After a teardown and before a discovery, the proxy will not
//! retransmit packets and interpret quACKs.
//!
//! Each Discovery packet is prefixed by a constant MAGIC.
//!
//! Note that, as of now, each sidekick connection is tied to a single
//! base connection.

use crate::{buffer::{AddrKey, UdpHeaders}, BUFFER_SIZE};
use serde::{Deserialize, Serialize};
use log::trace;

const MAGIC: [u8; 6] = *b"SKDISC";

/// Suggested number of ms to wait for a discovery ACK before retrying
pub const DISCOVERY_FREQ_MS: u64 = 50;
/// Suggested number of discovery packets to send at a time
pub const NUM_DISCOVERY_PKTS: usize = 3;

#[derive(Debug, Serialize, Deserialize, Eq, PartialEq, Clone)]
pub enum DiscoveryOp {
    Discover = 0,
    DiscoverAck = 1,
    Teardown = 2,
    TeardownAck = 3,
}

/// The first packet on a sidekick connection.
/// Should identify the corresponding base connection.
#[derive(Debug, Serialize, Deserialize)]
pub struct DiscoveryPayload {
    /// Identifies the packet as Sidekick Discovery.
    pub magic: [u8; 6],
    /// Identifies the discovery packet type.
    pub op: DiscoveryOp,
    /// Four-tuple (src_ip, src_port, dst_ip, dst_port) of the
    /// base connection from the perspective of the server (sender).
    /// Fields should be in NBO.
    pub base_connection_stoc: AddrKey,
}

impl DiscoveryPayload {
    pub fn new(
        base_connection_stoc: AddrKey,
        op: DiscoveryOp
    ) -> Self {
        trace!("Creating new DiscoveryPayload for base connection {}, {:?}",
               base_connection_stoc.iter()
                                   .map(|b| format!("{:02x}", b))
                                   .collect::<String>(), op);
        Self {
            magic: MAGIC,
            op,
            base_connection_stoc,
        }
    }

    pub fn from_payload(data: &[u8]) -> Option<Self> {
        let payload: DiscoveryPayload = bincode::deserialize(data).ok()?;
        if payload.magic != MAGIC {
            return None;
        }
        Some(payload)
    }

    pub fn to_payload(&self) -> Vec<u8> {
        bincode::serialize(&self).unwrap()
    }

    pub fn build_ack_payload(&self) -> Self {
        let op = match self.op {
            DiscoveryOp::Discover => DiscoveryOp::DiscoverAck,
            DiscoveryOp::Teardown => DiscoveryOp::TeardownAck,
            _ => panic!("Invalid operation for ack"),
        };
        Self::new(self.base_connection_stoc, op)
    }

    /// Given a DISCOVER DiscoveryPayload, the full packet it came in, and an output buffer,
    /// create a full DiscoveryAck packet, including swapping the UDP four-tuple.
    /// Write this to `buf`. This consumes `self`.
    /// Returns the length of the packet or an error.
    pub fn build_ack_packet(mut self, buf: &mut [u8; BUFFER_SIZE], packet: &[u8; BUFFER_SIZE]) -> Result<usize, std::io::Error>{
        self.op = DiscoveryOp::DiscoverAck;
        let payload = self.to_payload();
        let headers = UdpHeaders::_parse(packet).ok_or(std::io::Error::new(std::io::ErrorKind::InvalidData, "Invalid packet"))?;
        let headers = UdpHeaders {
            src_mac: headers.dst_mac,
            dst_mac: headers.src_mac,
            src_ip: headers.dst_ip,
            dst_ip: headers.src_ip,
            src_port: headers.dst_port,
            dst_port: headers.src_port,
        };
        headers.to_udp_packet(
            buf,
            payload,
        )
    }

}