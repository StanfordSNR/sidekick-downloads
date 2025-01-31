use std::fmt;
use std::error::Error;
use quack::{PowerSumQuack, PowerSumQuackU32};
use crate::stream::Packet;
use crate::identifier::{Identifier, IdentifierFunc};

/// The packets in a quACKnowledgment that are currently in the cache.
///
/// Indexes refer to the index in the ordered cache view.
#[derive(Debug, PartialEq, Eq)]
pub struct DecodeResult {
    /// One *plus* the index of the latest acknowledged packet.
    /// The value is 0 if no packets are acknowledged.
    pub last_index: usize,
    /// Indexes of packets before the latest acknowledged packet that were
    /// not acknowledged, in increasing order.
    pub missing_indexes: Vec<usize>,
}

/// Types of errors when decoding the quACK.
#[derive(Debug, PartialEq, Eq)]
pub enum DecodeError {
    /// Number of missing packets exceeds threshold.
    ExceededThreshold,
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            DecodeError::ExceededThreshold =>
                write!(f, "Number of missing packets exceeds threshold"),
        }
    }
}

impl Error for DecodeError {}

/// A cache of packets that is able to decode quACKs.
///
/// The quACKs represent all packets that have ever been added to the cache,
/// including those that have already been evicted.
pub struct QuackCache {
    /// The same length as `identifiers`.
    packet_cache: Vec<Packet>,
    /// The same length as `packets`.
    id_cache: Vec<Identifier>,
    /// The function used for calculating identifiers from packets.
    id_func: IdentifierFunc,
}

impl QuackCache {
    /// Initialize a new cache.
    pub fn new(id_func: IdentifierFunc) -> Self {
        Self {
            packet_cache: vec![],
            id_cache: vec![],
            id_func,
        }
    }

    /// The number of packets in the cache.
    pub fn len(&self) -> usize {
        self.packet_cache.len()
    }

    /// Return a read-only view of packets in the cache, ordered from least
    /// to most recently added.
    pub fn view(&self) -> &[Packet] {
        self.packet_cache.as_slice()
    }

    /// Add a packet to the cache.
    pub fn add(&mut self, packet: Packet) {
        self.id_cache.push(self.id_func.to_id(&packet.data));
        self.packet_cache.push(packet);
    }

    /// Get the i-th packet (0-indexing) in the ordered cache view.
    pub fn get(&self, i: usize) -> Option<&Packet> {
        self.packet_cache.get(i)
    }

    /// Evict the `n` least recently added packets from the cache.
    ///
    /// If there aren't at least `n` packets to evict, returns an error without
    /// modifying the cache.
    pub fn evict(&mut self, n: usize) -> Result<(), Box<dyn Error>> {
        if n <= self.len() {
            self.id_cache.drain(0..n);
            self.packet_cache.drain(0..n);
            Ok(())
        } else {
            Err("not enough packets to evict".into())
        }
    }

    /// Reset the cache.
    pub fn reset(&mut self) {
        self.id_cache = vec![];
        self.packet_cache = vec![];
    }

    /// The quACK represents all packets that have ever been added to the
    /// cache, including those that have already been evicted. The decoded
    /// result communicates which packets currently in the cache the quACK
    /// is acknowledging.
    ///
    /// The quACK fails to decode if
    /// Returns None if we should send a reset and also reset the cache.
    pub fn decode(
        &self, quack: &PowerSumQuackU32,
    ) -> Result<DecodeResult, DecodeError> {
        unimplemented!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_packet(data: &[u8]) -> Packet {
        let mut pkt = Packet::new(0);
        assert!(data.len() <= pkt.data.len());
        pkt.nbytes = data.len() as _;
        pkt.data[..data.len()].copy_from_slice(data);
        pkt
    }

    #[test]
    fn test_new_quack_cache() {
        let cache = QuackCache::new(IdentifierFunc::FirstByte);
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
    }

    #[test]
    fn test_add_and_view() {
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        let packet1 = test_packet(&[1, 2, 3]);
        let packet2 = test_packet(&[4, 5, 6]);

        cache.add(packet1.clone());
        cache.add(packet2.clone());

        let view = cache.view();
        assert_eq!(view.len(), 2);
        assert_eq!(view[0], packet1);
        assert_eq!(view[1], packet2);
    }

    #[test]
    fn test_add_and_get() {
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        let packet1 = test_packet(&[1, 2, 3]);
        let packet2 = test_packet(&[4, 5, 6]);

        cache.add(packet1.clone());
        cache.add(packet2.clone());

        assert_eq!(cache.get(0), Some(&packet1));
        assert_eq!(cache.get(1), Some(&packet2));
        assert_eq!(cache.get(2), None);
    }

    #[test]
    fn test_evict_success() {
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));
        cache.add(test_packet(&[3]));

        // evict partial
        assert!(cache.evict(2).is_ok());
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.view().len(), 1);
        assert_eq!(cache.get(0), Some(&test_packet(&[3])));

        // evict full
        assert!(cache.evict(1).is_ok());
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
        assert_eq!(cache.get(0), None);
    }

    #[test]
    fn test_evict_error() {
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));
        cache.add(test_packet(&[3]));
        assert!(cache.evict(4).is_err());
        assert!(cache.evict(3).is_ok());
        assert!(cache.evict(1).is_err());
    }

    #[test]
    fn test_reset() {
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        cache.add(test_packet(&[1]));
        cache.reset();
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
    }

    #[test]
    fn test_decode_none_missing() {
        let threshold = 4;
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(threshold);
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }

        // all packets are acked
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![]);

        // add more packets - a strict prefix is acked
        cache.add(test_packet(&[43]));
        cache.add(test_packet(&[27]));
        cache.add(test_packet(&[36]));
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![]);

        // evict some packets
        let num_to_evict = 5;
        assert!(cache.evict(num_to_evict).is_ok());
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets - num_to_evict);
        assert_eq!(res.missing_indexes, vec![]);
    }

    #[test]
    fn test_decode_some_missing() {
        let threshold = 4;
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(threshold);
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }

        // remove "missing" packets from the quack
        q.remove(5);
        q.remove(6);
        q.remove(8);

        // detect missing packets
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![5, 6, 8]);

        // add more packets to the suffix - detect missing packets still
        cache.add(test_packet(&[43]));
        cache.add(test_packet(&[27]));
        cache.add(test_packet(&[36]));
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![5, 6, 8]);

        // evict some packets
        let num_to_evict = 5;
        assert!(cache.evict(num_to_evict).is_ok());
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets - num_to_evict);
        assert_eq!(res.missing_indexes, vec![0, 1, 3]);
    }

    #[test]
    fn test_decode_exceeded_threshold() {
        let threshold = 4;
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(threshold);
        let mut cache = QuackCache::new(IdentifierFunc::FirstByte);
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }

        // remove "missing" packets from the quack
        q.remove(2);
        q.remove(3);
        q.remove(5);
        q.remove(6);
        q.remove(8);

        // exceeded threshold
        let res = cache.decode(&q);
        assert!(res.is_err());
        assert_eq!(res.unwrap_err(), DecodeError::ExceededThreshold);
    }
}
