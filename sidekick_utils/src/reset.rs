//! Packet for resetting a sidekick connection.
//!
//! The quACK receiver sends a Reset packet when it is unable to decode the
//! received quACK in order to try to "reset" both endpoints of a sidekick
//! connection to a consistent state. The receiver will wait a fixed duration
//! before sending another reset, to allow the quACK sender time to process
//! the reset.
//!
//! Upon sending/receiving a Reset packet, the quACK receiver/sender will reset
//! its quACK to a fresh state with no accumualted packets.
//!
//! Each Reset packet is prefixed by a constant MAGIC.

use crate::{buffer::UdpHeaders, BUFFER_SIZE};
use serde::{Deserialize, Serialize};

const MAGIC: [u8; 6] = *b"SRESET";

/// Suggested number of ms to wait for between sending resets if the state is
/// still not consistent
pub const RESET_FREQ_MS: u64 = 50;

/// The UDP payload of a Reset packet from the quACK receiver.
#[derive(Debug, Serialize, Deserialize)]
pub struct ResetPayload {
    /// Identifies the packet as Sidekick Reset.
    pub magic: [u8; 6],
}

impl ResetPayload {
    pub fn new() -> Self {
        Self { magic: MAGIC }
    }

    pub fn from_payload(data: &[u8]) -> Option<Self> {
        let payload: ResetPayload = bincode::deserialize(data).ok()?;
        if payload.magic != MAGIC {
            return None;
        }
        Some(payload)
    }

    pub fn to_payload(&self) -> Vec<u8> {
        bincode::serialize(&self).unwrap()
    }

    /// Given the full packet of the quACK it is responding to, and an output
    /// buffer, create a full Reset packet, including swapping the UDP four-tuple.
    /// Write this to `buf`.
    /// Returns the length of the packet or an error.
    pub fn build_packet(buf: &mut [u8; BUFFER_SIZE], packet: &[u8; BUFFER_SIZE]) -> Result<usize, std::io::Error>{
        let payload = ResetPayload::new().to_payload();
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