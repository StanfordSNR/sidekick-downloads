use crate::{buffer::UdpHeaders, BUFFER_SIZE};
use serde::{Deserialize, Serialize};

const MAGIC: [u8; 6] = *b"SRETX!";

/// The UDP payload of a Reset packet from the quACK receiver.
#[derive(Debug, Serialize, Deserialize)]
pub struct RetransmitPayload {
    /// Identifies the packet as Sidekick Retransmit.
    pub magic: [u8; 6],
    pub data: Vec<u8>,
}

impl RetransmitPayload {
    pub fn new(data: &[u8]) -> Self {
        Self { magic: MAGIC, data: data.to_vec() }
    }

    pub fn from_payload(data: &[u8]) -> Option<Self> {
        let payload: RetransmitPayload = bincode::deserialize(data).ok()?;
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
    pub fn build_packet(self, buf: &mut [u8; BUFFER_SIZE], packet: &[u8; BUFFER_SIZE]) -> Result<usize, std::io::Error>{
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
