use sidekick_utils::BUFFER_SIZE;

use crate::ack::BlockAck;

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
        unimplemented!()
    }

    pub fn new_outer(data: &[u8]) -> Self {
        unimplemented!()
    }
}
