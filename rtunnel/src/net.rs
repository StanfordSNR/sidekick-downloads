use sidekick_utils::BUFFER_SIZE;

use crate::ack::BlockAck;

const ETHERNET_HEADER_LEN: usize = 14;

pub enum Packet {
    Inner {
        ip_datagram: Vec<u8>,
    },
    Outer {
        seqno: u32,
        ip_datagram: Vec<u8>,
    },
    Ack(BlockAck),
}

impl Packet {
    pub fn parse_inner(data: &[u8]) -> Self {
        Packet::Inner {
            ip_datagram: data[ETHERNET_HEADER_LEN..].to_vec(),
        }
    }

    pub fn parse_outer(udp_payload: &[u8]) -> Self {
        let is_ack = udp_payload[0] != 0;
        if is_ack {
            assert_eq!(udp_payload.len(), 9);
            let seqno = u32::from_be_bytes([
                udp_payload[1],
                udp_payload[2],
                udp_payload[3],
                udp_payload[4],
            ]);
            let block = u32::from_be_bytes([
                udp_payload[5],
                udp_payload[6],
                udp_payload[7],
                udp_payload[8],
            ]);
            Packet::Ack(BlockAck { seqno, block })
        } else {
            Packet::Outer {
                seqno: u32::from_be_bytes([
                    udp_payload[1],
                    udp_payload[2],
                    udp_payload[3],
                    udp_payload[4],
                ]),
                ip_datagram: udp_payload[5..].to_vec(),
            }
        }
    }

    pub fn serialize(&self, buf: &mut [u8; BUFFER_SIZE]) -> usize {
        match self {
            Packet::Inner { .. } => panic!("serialize it yourself"),
            Packet::Outer { seqno, ip_datagram } => {
                buf[0] = 0; // !is_ack
                buf[1..5].copy_from_slice(&u32::to_be_bytes(*seqno)[..]);
                buf[5..5+ip_datagram.len()].copy_from_slice(ip_datagram.as_slice());
                5 + ip_datagram.len()
            }
            Packet::Ack(ack) => {
                buf[0] = 1; // is_ack
                buf[1..5].copy_from_slice(&u32::to_be_bytes(ack.seqno)[..]);
                buf[5..9].copy_from_slice(&u32::to_be_bytes(ack.block)[..]);
                9
            }
        }
    }
}
