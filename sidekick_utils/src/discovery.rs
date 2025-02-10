use crate::buffer::AddrKey;
use serde::{Deserialize, Serialize};

const MAGIC: [u8; 6] = *b"SKDISC";

/// The first packet on a sidekick connection.
/// Should identify the corresponding base connection.
#[derive(Debug, Serialize, Deserialize)]
pub struct DiscoveryPayload {
    /// Identifies the packet as Sidekick Discovery.
    pub magic: [u8; 6],
    /// Four-tuple (src_ip, src_port, dst_ip, dst_port) of the
    /// base connection from the perspective of the client (receiver).
    /// Fields should be in NBO.
    pub base_connection_ctos: AddrKey,
}

impl DiscoveryPayload {
    pub fn new(
        base_connection_ctos: AddrKey,
    ) -> Self {
        Self {
            magic: MAGIC,
            base_connection_ctos,
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