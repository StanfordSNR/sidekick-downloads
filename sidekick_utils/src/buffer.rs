use libc::c_uchar;
use crate::{fmt_hex, BUFFER_SIZE};
use crate::identifier::{IdentifierFunc, Identifier};

use pnet::packet::ethernet::{MutableEthernetPacket, EtherTypes};
use pnet::packet::ip::IpNextHeaderProtocols;
use pnet::packet::ipv4::MutableIpv4Packet;
use pnet::packet::ipv4;
use pnet::packet::udp::MutableUdpPacket;
use pnet::datalink::MacAddr;
use std::net::Ipv4Addr;
use log::trace;

// Ethernet (14), IP (20), TCP/UDP (8) headers
const ETH_HDR_LEN: usize = 14;
const IPV4_HDR_LEN: usize = 20;
const UDP_HDR_LEN: usize = 8;
const UDP_PAYLOAD_OFFSET: usize = 42;

/// UDP four-tuple: src_ip, src_port, dst_ip, dst_port (UDP)
/// Fields expected to be read from packets; should be in NBO
pub type AddrKey = [u8; 12];

#[derive(Debug, PartialEq, Eq)]
pub enum Direction {
    Incoming,
    Outgoing,
    Unknown,
}

// https://github.com/torvalds/linux/blob/master/include/uapi/linux/if_packet.h
pub const PACKET_HOST: c_uchar = 0;
pub const PACKET_OTHERHOST: c_uchar = 3;
pub const PACKET_OUTGOING: c_uchar = 4;

impl From<c_uchar> for Direction {
    fn from(val: c_uchar) -> Self {
        match val {
            PACKET_HOST | PACKET_OTHERHOST => Direction::Incoming,
            PACKET_OUTGOING => Direction::Outgoing,
            _ => Direction::Unknown,
        }
    }
}

pub struct UdpParser {
    pub src_mac: String,
    pub dst_mac: String,
    pub src_ip: String,
    pub dst_ip: String,
    pub src_port: u16,
    pub dst_port: u16,
    pub identifier: Identifier,
}

impl UdpParser {
    pub fn _parse(x: &[u8; BUFFER_SIZE], identifier: IdentifierFunc) -> Option<Self> {
        let ip_protocol = x[23];
        if i32::from(ip_protocol) != libc::IPPROTO_UDP {
            return None;
        }

        let src_mac = x[0..4]
            .iter()
            .map(|b| format!("{:x}", b))
            .collect::<Vec<_>>()
            .join(":");
        let dst_mac = x[4..8]
            .iter()
            .map(|b| format!("{:x}", b))
            .collect::<Vec<_>>()
            .join(":");
        let src_ip = format!("{}.{}.{}.{}", x[26], x[27], x[28], x[29]);
        let dst_ip = format!("{}.{}.{}.{}", x[30], x[31], x[32], x[33]);
        let src_port = u16::from_be_bytes([x[34], x[35]]);
        let dst_port = u16::from_be_bytes([x[36], x[37]]);
        let identifier = identifier.to_id(x);
        Some(UdpParser {
            src_mac,
            dst_mac,
            src_ip,
            dst_ip,
            identifier,
            src_port,
            dst_port,
        })
    }

    /// Returns True if and only if the buffer represents a UDP packet.
    pub fn is_udp(x: &[u8; BUFFER_SIZE]) -> bool {
        let ip_protocol = x[23];
        i32::from(ip_protocol) == libc::IPPROTO_UDP
    }

    /// Returns src IP (IPv4) in NBO
    pub fn parse_src_ip(x: &[u8; BUFFER_SIZE]) -> [u8; 4] {
        [x[26], x[27], x[28], x[29]]
    }

    /// Returns src UDP port in NBO
    pub fn parse_src_port(x: &[u8; BUFFER_SIZE]) -> [u8; 2] {
        [x[34], x[35]]
    }

    /// src_ip, src_port, dst_ip, dst_port
    pub fn parse_addr_key(x: &[u8; BUFFER_SIZE]) -> AddrKey {
        [
            x[26], x[27], x[28], x[29], x[34], x[35], x[30], x[31], x[32], x[33], x[36], x[37],
        ]
    }

    /// Flip AddrKey to be dst_ip, dst_port, src_ip, src_port
    pub fn flip_addr_key(mut x: AddrKey) -> AddrKey {
        let (src, dst) = x.split_at_mut(6);
        src.swap_with_slice(dst);
        x
    }

    /// Returns the dst_port assuming the buffer represents a UDP packet.
    pub fn parse_dst_port(x: &[u8; BUFFER_SIZE]) -> u16 {
        u16::from_be_bytes([x[36], x[37]])
    }

    /// Returns the UDP payload.
    /// nbytes is the number of bytes in the entire packet
    pub fn payload(x: &[u8; BUFFER_SIZE], nbytes: usize) -> &[u8] {
        &x[crate::UDP_PAYLOAD_OFFSET..nbytes]
    }

    /// Returns the sidekick identifier assuming the buffer
    /// represents a QUIC UDP packet.
    pub fn parse_identifier(x: &[u8; BUFFER_SIZE], identifier: IdentifierFunc) -> Identifier {
        identifier.to_id(x)
    }

}

// All fields should be in NBO
pub struct UdpHeaders {
    pub src_mac: [u8; 6],
    pub dst_mac: [u8; 6],
    pub src_ip: [u8; 4],
    pub dst_ip: [u8; 4],
    pub src_port: [u8; 2],
    pub dst_port: [u8; 2],
}

impl UdpHeaders {
    /// Parse from raw packet
    pub fn _parse(x: &[u8; BUFFER_SIZE]) -> Option<Self> {
        let ip_protocol = x[23];
        if i32::from(ip_protocol) != libc::IPPROTO_UDP {
            return None;
        }

        Some(UdpHeaders {
            src_mac: x[6..12].try_into().unwrap(),
            dst_mac: x[0..6].try_into().unwrap(),
            src_ip: x[26..30].try_into().unwrap(),
            dst_ip: x[30..34].try_into().unwrap(),
            src_port: x[34..36].try_into().unwrap(),
            dst_port: x[36..38].try_into().unwrap(),
        })
    }

    /// Builds a raw UDP packet, placing it in `buf`. Returns
    /// the length of the packet, or an error if the payload is too large.
    /// All fields must be in NBO.
    pub fn to_udp_packet(&self, buf: &mut [u8; BUFFER_SIZE], payload: Vec<u8>) -> Result<usize, std::io::Error> {
        let len = UDP_PAYLOAD_OFFSET + payload.len();
        if  len > BUFFER_SIZE {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidInput,
                                format!("Payload ({} bytes) must be <= {} bytes",
                                                payload.len(), BUFFER_SIZE - UDP_PAYLOAD_OFFSET)));
        }
        assert!(payload.len() <= u16::MAX as usize - 8); // Must fit in UDP payload

        trace!("Building UDP packet with payload length {} \
                Eth (NBO): {} -> {} \
                IP (NBO): {} -> {} \
                UDP (HBO): {} -> {}",
               payload.len(),
               fmt_hex!(self.src_mac),
               fmt_hex!(self.dst_mac),
               fmt_hex!(self.src_ip),
               fmt_hex!(self.dst_ip),
               u16::from_be_bytes(self.src_port),
               u16::from_be_bytes(self.dst_port));

        // Headers
        let mut eth = MutableEthernetPacket::new(&mut buf[..ETH_HDR_LEN]).unwrap();
        eth.set_destination(MacAddr::from(self.dst_mac));
        eth.set_source(MacAddr::from(self.src_mac));
        eth.set_ethertype(EtherTypes::Ipv4);
        let mut ip = MutableIpv4Packet::new(&mut buf[ETH_HDR_LEN..ETH_HDR_LEN + IPV4_HDR_LEN]).unwrap();
        ip.set_version(4);
        ip.set_header_length(5);
        ip.set_total_length((IPV4_HDR_LEN + UDP_HDR_LEN + payload.len()) as u16);
        ip.set_next_level_protocol(IpNextHeaderProtocols::Udp);
        ip.set_source(Ipv4Addr::from(self.src_ip));
        ip.set_destination(Ipv4Addr::from(self.dst_ip));
        ip.set_ttl(64);
        ip.set_checksum(ipv4::checksum(&ip.to_immutable()));
        let mut udp = MutableUdpPacket::new(&mut buf[ETH_HDR_LEN + IPV4_HDR_LEN..len]).unwrap();
        udp.set_source(u16::from_be_bytes(self.src_port));
        udp.set_destination(u16::from_be_bytes(self.dst_port));
        udp.set_length((UDP_HDR_LEN + payload.len()) as u16);
        udp.set_checksum(0); // offloaded or optional
        udp.set_payload(&payload);

        return Ok(len);
    }
}