use crate::{buffer::{AddrKey, UdpHeaders}, BUFFER_SIZE};
use serde::{Deserialize, Serialize};
use log::trace;

const MAGIC: [u8; 6] = *b"SKDISC";

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