use std::fmt;
use std::error::Error;
use quack::{PowerSumQuack, PowerSumQuackU32};
use crate::stream::Packet;
use crate::identifier::{Identifier, IdentifierFunc};

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
        unimplemented!()
    }

    /// The number of packets in the cache.
    pub fn len(&self) -> usize {
        unimplemented!()
    }

    /// Return a read-only view of packets in the cache, ordered from least
    /// to most recently added.
    pub fn view(&self) -> &[Packet] {
        unimplemented!()
    }

    /// Add a packet to the cache.
    pub fn add(&mut self, packet: Packet) {
        unimplemented!()
    }

    /// Get the i-th packet (0-indexing) in the ordered cache view.
    pub fn get(&self, i: usize) -> Option<&Packet> {
        unimplemented!()
    }

    /// Evict the `n` least recently added packets from the cache.
    ///
    /// If there aren't at least `n` packets to evict, returns an error without
    /// modifying the cache.
    pub fn evict(&mut self, n: usize) -> Result<(), Box<dyn Error>> {
        unimplemented!()
    }

    /// Reset the cache.
    pub fn reset(&mut self) {
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
}
