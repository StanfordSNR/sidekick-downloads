use crate::buffer::AddrKey;
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

}