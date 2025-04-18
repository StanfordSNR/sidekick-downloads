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
    pub fn new_inner(data: &[u8]) -> Self {
        Packet::Inner {
            ip_datagram: data[ETHERNET_HEADER_LEN..].to_vec(),
        }
    }

    pub fn new_outer(data: &[u8]) -> Self {
        Packet::Outer {
            seqno: 0,
            ip_datagram: data.to_vec(),
        }
    }
}
