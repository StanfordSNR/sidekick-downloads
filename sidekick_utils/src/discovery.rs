use crate::buffer::AddrKey;
use std::net::SocketAddr;
use serde::{Deserialize, Serialize};

const MAGIC: [u8; 6] = *b"SKDISC";

#[derive(Debug, Serialize, Deserialize)]
pub struct DiscoveryPayload {
    /// Identifies the packet as Sidekick Discovery.
    pub magic: [u8; 6],
    /// Four-tuple (src_ip, src_port, dst_ip, dst_port) of the
    /// base connection from the perspective of the client (receiver).
    /// Fields should be in NBO.
    pub base_connection_ctos: AddrKey,
    /// Four-tuple of the associated sidekick connection.
    /// Fields should be in NBO.
    pub sidekick_connection: AddrKey,
}

impl DiscoveryPayload {
    pub fn new(
        sidekick_src: SocketAddr,
        sidekick_dst: SocketAddr,
        base_connection_ctos: AddrKey,
    ) -> Self {
        let src_port = sidekick_src.port().to_be_bytes();
        let dst_port = sidekick_dst.port().to_be_bytes();

        // IP address returned by `octets()` already in NBO
        // (Note: the `bits` method would be in HBO)
        let src_ip = match sidekick_src.ip() {
            std::net::IpAddr::V4(ip) => ip.octets(),
            std::net::IpAddr::V6(_) => panic!(),
        };
        let dst_ip = match sidekick_dst.ip() {
            std::net::IpAddr::V4(ip) => ip.octets(),
            std::net::IpAddr::V6(_) => panic!(),
        };

        let mut sidekick_connection = [0; 12];
        sidekick_connection[..4].copy_from_slice(&src_ip);
        sidekick_connection[4..6].copy_from_slice(&src_port);
        sidekick_connection[6..10].copy_from_slice(&dst_ip);
        sidekick_connection[10..12].copy_from_slice(&dst_port);

        Self {
            magic: MAGIC,
            base_connection_ctos,
            sidekick_connection,
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