use sidekick_utils::identifier::{Identifier, IdentifierFunc};
use crate::stream::Packet;
use log::trace;
use quack::{arithmetic::ModularArithmetic, PowerSumQuack, PowerSumQuackU32};
use std::error::Error;
use std::fmt;

/// The packets in a quACKnowledgment that are currently in the cache.
///
/// Indexes refer to the index in the ordered cache view.
#[derive(Debug, PartialEq, Eq, Default, Clone)]
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
    /// The client should only send quACKs if it has observed at least 1 packet.
    EmptyClientQuack,
    /// The threshold of the received quACK does not match our own threshold.
    InvalidThreshold { expected: usize, actual: usize },
    /// Number of missing packets exceeds threshold.
    ExceededThreshold {
        num_missing: usize,
        threshold: usize,
    },
    /// The last value the client received is not an identifier of a known
    /// packet that is currently or was previously in our cache.
    MissingLastValue { identifier: Identifier },
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            DecodeError::EmptyClientQuack => {
                write!(f, "Empty client quack")
            }
            DecodeError::InvalidThreshold { expected, actual } => {
                write!(f, "Invalid threshold {} != {}", expected, actual)
            }
            DecodeError::ExceededThreshold {
                num_missing,
                threshold,
            } => write!(
                f,
                "Number of missing packets exceeds threshold {} > {}",
                num_missing, threshold
            ),
            DecodeError::MissingLastValue { identifier } => {
                write!(f, "Missing last value {}", identifier)
            }
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

    quack: PowerSumQuackU32,
    last_decode_result: DecodeResult,

    /// Cache capacity. Incoming packets >= this capacity will be dropped.
    capacity: usize,
}

impl QuackCache {
    /// Initialize a new cache.
    pub fn new(id_func: IdentifierFunc, quack_threshold: usize, capacity: usize) -> Self {
        Self {
            packet_cache: vec![],
            id_cache: vec![],
            id_func,
            quack: PowerSumQuackU32::new(quack_threshold),
            last_decode_result: DecodeResult::default(),
            capacity
        }
    }

    /// The number of packets in the cache.
    pub fn len(&self) -> usize {
        debug_assert!(self.packet_cache.len() <= self.capacity);
        self.packet_cache.len()
    }

    /// Return a read-only view of packets in the cache, ordered from least
    /// to most recently added.
    pub fn view(&self) -> &[Packet] {
        self.packet_cache.as_slice()
    }

    /// Add a packet to the cache.
    pub fn add(&mut self, packet: Packet) {
        if self.len() >= self.capacity {
            trace!("At capacity {}; dropping packet", self.capacity);
            return;
        }
        self.id_cache.push(self.id_func.to_id(&packet.data));
        self.packet_cache.push(packet);
    }

    /// Get the i-th packet (0-indexing) in the ordered cache view.
    pub fn get(&self, i: usize) -> Option<&Packet> {
        self.packet_cache.get(i)
    }

    /// Evict the `n` least recently added packets from the cache.
    ///
    /// The evicted packets must have all been decided to be either received or
    /// lost based on the decode results of the last quACK. Eviction makes these
    /// decisions final.
    ///
    /// If there aren't at least `n` packets to evict, returns an error without
    /// modifying the cache.
    pub fn evict(&mut self, n: usize) -> Result<(), Box<dyn Error>> {
        if n > self.len() {
            return Err("not enough packets to evict".into());
        }
        if n > self.last_decode_result.last_index {
            return Err("quack hasn't made decision on packet fates".into());
        }

        // Make missing packet decisions final
        let mut missing_indexes = vec![];
        for &index in &self.last_decode_result.missing_indexes {
            if index < n {
                self.quack.remove(self.id_cache[index]);
            } else {
                missing_indexes.push(index - n);
            }
        }

        // Make received packet decisions final and evict from caches
        for id in self.id_cache.drain(0..n) {
            self.quack.insert(id);
        }
        self.packet_cache.drain(0..n);

        // Update last decode result
        self.last_decode_result.last_index -= n;
        self.last_decode_result.missing_indexes = missing_indexes;
        Ok(())
    }

    /// Reset the cache.
    pub fn reset(&mut self) {
        self.id_cache = vec![];
        self.packet_cache = vec![];
    }

    /// The quACK is the cumulative representation of all packets that have ever
    /// been added to the cache that the client has actually received, including
    /// those that have already been evicted. The decoded result communicates
    /// which packets that are *currently* in the cache are being quACKed.
    ///
    /// Modifies the internal decisions of which packets have been definitively
    /// received or likely lost. On eviction, these decisions are made final.
    ///
    /// Returns an error if the quACK fails to decode.
    pub fn decode(&mut self, client_quack: &PowerSumQuackU32) -> Result<DecodeResult, DecodeError> {
        // Check empty client quACK
        if client_quack.last_value().is_none() {
            return Err(DecodeError::EmptyClientQuack);
        }

        // Check invalid threshold
        if self.quack.threshold() != client_quack.threshold() {
            return Err(DecodeError::InvalidThreshold {
                expected: self.quack.threshold(),
                actual: client_quack.threshold(),
            });
        }

        // Insert ids in the id cache up to the last id received by the client.
        // Assuming the client receives a subset of packets in the cache, if
        // the last value doesn't exist in our cache, then the state is
        // corrupted either by an early eviction or network packet corruption.
        let mut last_index = 0;
        let mut proxy_quack = self.quack.clone();
        for &id in &self.id_cache {
            if proxy_quack.last_value() == client_quack.last_value() {
                break;
            }
            proxy_quack.insert(id);
            last_index += 1;
        }
        if proxy_quack.last_value() != client_quack.last_value() {
            return Err(DecodeError::MissingLastValue {
                identifier: client_quack.last_value().unwrap(),
            });
        }

        // Check that the number of missing packets is within the threshold.
        // Note that it's possible for weird behavior to occur with overflows,
        // but the state is invalid in either case.
        let difference_quack = proxy_quack.sub(client_quack.clone());
        if (difference_quack.count() as usize) > difference_quack.threshold() {
            return Err(DecodeError::ExceededThreshold {
                num_missing: difference_quack.count() as usize,
                threshold: difference_quack.threshold(),
            });
        }

        // Decode the quACK using the identifier cache.
        let result = if difference_quack.count() == 0 {
            DecodeResult {
                last_index,
                missing_indexes: vec![],
            }
        } else {
            let coeffs = difference_quack.to_coeffs();
            let missing_indexes = self
                .id_cache
                .iter()
                .take(last_index)
                .enumerate()
                .filter(|(_, &id)| quack::arithmetic::eval(&coeffs, id).value() == 0)
                .map(|(index, _)| index)
                .collect();
            DecodeResult {
                last_index,
                missing_indexes,
            }
        };

        // Cache the result.
        self.last_decode_result = result.clone();
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DEFAULT_THRESHOLD: usize = 4;
    const DEFAULT_CAPACITY: usize = 30;

    fn new_cache() -> QuackCache {
        QuackCache::new(IdentifierFunc::FirstByte, DEFAULT_THRESHOLD,
                        DEFAULT_CAPACITY)
    }

    fn test_packet(data: &[u8]) -> Packet {
        let mut pkt = Packet::new(0);
        assert!(data.len() <= pkt.data.len());
        pkt.nbytes = data.len() as _;
        pkt.data[..data.len()].copy_from_slice(data);
        pkt
    }

    #[test]
    fn test_new_quack_cache() {
        let cache = new_cache();
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
    }

    #[test]
    fn test_add_and_view() {
        let mut cache = new_cache();
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
        let mut cache = new_cache();
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
        let mut cache = new_cache();
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));
        cache.add(test_packet(&[3]));

        // quack all packets
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        q.insert(1);
        q.insert(2);
        q.insert(3);
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 3);
        assert_eq!(res.missing_indexes, vec![]);

        // evict partial
        assert!(cache.evict(2).is_ok());
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.view().len(), 1);
        assert_eq!(cache.get(0), Some(&test_packet(&[3])));
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 1);
        assert_eq!(res.missing_indexes, vec![]);

        // evict full
        assert!(cache.evict(1).is_ok());
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
        assert_eq!(cache.get(0), None);
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 0);
        assert_eq!(res.missing_indexes, vec![]);
    }

    #[test]
    fn test_evict_error() {
        let mut cache = new_cache();
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));
        cache.add(test_packet(&[3]));

        // try to evict before decode
        assert!(cache.evict(3).is_err());

        // quack all packets
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        q.insert(1);
        q.insert(2);
        q.insert(3);
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 3);
        assert_eq!(res.missing_indexes, vec![]);

        // try to evict after decode
        assert!(cache.evict(4).is_err());
        assert!(cache.evict(3).is_ok());
        assert!(cache.evict(1).is_err());
    }

    #[test]
    fn test_reset() {
        let mut cache = new_cache();
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
        let mut cache = new_cache();
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
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();
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
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();
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
        assert_eq!(
            res.unwrap_err(),
            DecodeError::ExceededThreshold {
                num_missing: 5,
                threshold: DEFAULT_THRESHOLD,
            }
        );
    }

    #[test]
    fn test_add_capacity() {
        let mut cache = new_cache();
        for i in 0..DEFAULT_CAPACITY as u8 {
            cache.add(test_packet(&[i]));
        }

        assert_eq!(cache.len(), DEFAULT_CAPACITY);
        assert_eq!(cache.view().len(), DEFAULT_CAPACITY);

        // Adding the extra packet should have no impact
        cache.add(test_packet(&[DEFAULT_CAPACITY as _]));
        assert_eq!(cache.len(), DEFAULT_CAPACITY);
        assert_eq!(cache.view().len(), DEFAULT_CAPACITY);
    }
}
