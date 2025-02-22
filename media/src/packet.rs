//! Wire format of the packets sent in the dummy media application.
//!
//! The first four bytes of the payload indicate a packet sequence number,
//! where the sequence numbers start at 1. The next byte indicates whether
//! the packet is a NACK. Four bytes at a given offset indicate a random
//! identifier to be parsed by the sidekicks.
use rand::{self, Rng};
use crate::{PAYLOAD_SIZE, PAYLOAD_ID_OFFSET, TIMEOUT_SEQNO};


#[derive(Debug, Clone)]
pub struct Packet {
    pub seqno: u32,
    pub is_nack: bool,
    pub identifier: u32,
}

impl Packet {
    pub fn new_data(seqno: u32) -> Self {
        Packet {
            seqno,
            is_nack: false,
            identifier: rand::thread_rng().gen(),
        }
    }

    pub fn new_nack(seqno: u32) -> Self {
        Packet {
            seqno,
            is_nack: true,
            identifier: rand::thread_rng().gen(),
        }
    }

    pub fn from_payload(buf: &[u8; PAYLOAD_SIZE]) -> Self {
        let seqno = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]);
        let is_nack = buf[5] == 1;
        let identifier = u32::from_be_bytes([
            buf[PAYLOAD_ID_OFFSET],
            buf[PAYLOAD_ID_OFFSET + 1],
            buf[PAYLOAD_ID_OFFSET + 2],
            buf[PAYLOAD_ID_OFFSET + 3],
        ]);
        Self { seqno, is_nack, identifier }
    }

    pub fn fill_payload(&self, buf: &mut [u8; PAYLOAD_SIZE]) {
        // Set the sequence number in the first 4 bytes.
        let seqno_bytes = self.seqno.to_be_bytes();
        buf[0] = seqno_bytes[0];
        buf[1] = seqno_bytes[1];
        buf[2] = seqno_bytes[2];
        buf[3] = seqno_bytes[3];

        // Set the next byte to whether the packet is a NACK.
        buf[5] = if self.is_nack { 1 } else { 0 };

        // Set the random packet identifier at the QUIC offset.
        let id_bytes = self.identifier.to_be_bytes();
        buf[PAYLOAD_ID_OFFSET] = id_bytes[0];
        buf[PAYLOAD_ID_OFFSET + 1] = id_bytes[1];
        buf[PAYLOAD_ID_OFFSET + 2] = id_bytes[2];
        buf[PAYLOAD_ID_OFFSET + 3] = id_bytes[3];
    }

    pub fn is_timeout(&self) -> bool {
        self.seqno == TIMEOUT_SEQNO
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_data_packet_unique_identifiers() {
        let p1 = Packet::new_data(1);
        assert!(!p1.is_nack);
        assert_eq!(p1.seqno, 1);
        let p2 = Packet::new_data(2);
        assert!(!p2.is_nack);
        assert_eq!(p2.seqno, 2);
        assert_ne!(p2.identifier, p1.identifier);
        let p3 = Packet::new_data(2);
        assert!(!p3.is_nack);
        assert_eq!(p3.seqno, 2);
        assert_ne!(p3.identifier, p1.identifier);
        assert_ne!(p3.identifier, p2.identifier);
    }

    #[test]
    fn test_data_packet_is_timeout() {
        let p = Packet::new_data(TIMEOUT_SEQNO);
        assert!(p.is_timeout());
        let p = Packet::new_data(TIMEOUT_SEQNO - 1);
        assert!(!p.is_timeout());
    }

    #[test]
    fn test_data_packet_fill_and_from_payload() {
        let p1 = Packet::new_data(12345);
        let mut payload = [0u8; PAYLOAD_SIZE];
        p1.fill_payload(&mut payload);
        let p2 = Packet::from_payload(&payload);
        assert!(!p2.is_nack);
        assert_eq!(p1.seqno, p2.seqno);
        assert_eq!(p1.identifier, p2.identifier);
    }

    #[test]
    fn test_nack_packet_new() {
        let p1 = Packet::new_nack(1);
        assert!(p1.is_nack);
        assert_eq!(p1.seqno, 1);
        let p2 = Packet::new_nack(2);
        assert!(p2.is_nack);
        assert_eq!(p2.seqno, 2);
        assert_ne!(p2.identifier, p1.identifier);
        let p3 = Packet::new_nack(2);
        assert!(p3.is_nack);
        assert_eq!(p3.seqno, 2);
        assert_ne!(p3.identifier, p1.identifier);
        assert_ne!(p3.identifier, p2.identifier);
    }

    #[test]
    fn test_nack_packet_to_and_from_payload() {
        let p1 = Packet::new_nack(12345);
        let mut payload = [0u8; PAYLOAD_SIZE];
        p1.fill_payload(&mut payload);
        let p2 = Packet::from_payload(&payload);
        assert!(p2.is_nack);
        assert_eq!(p1.seqno, p2.seqno);
        assert_eq!(p1.identifier, p2.identifier);
    }
}