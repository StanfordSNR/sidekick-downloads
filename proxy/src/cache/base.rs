use std::collections::{HashSet, VecDeque};
#[cfg(feature = "cache_statistics")]
use std::time::Instant;
use log::{trace, debug};
use sidekick_utils::{
    packet::CachePolicy,
    identifier::{Identifier, IdentifierFunc},
};
use quack::{arithmetic::ModularArithmetic, Quack, PowerSumQuack, QuackWrapper};

use crate::stream::Packet;
use crate::cache::{DecodeError, DecodeResult};
use crate::cycles::*;

#[cfg(feature = "cache_statistics")]
fn cache_log(event: &str, nbytes: usize) {
    debug!("cache_statistics {:?} {} {}", Instant::now(), event, nbytes);
}

/// A cache of packets that is able to decode quACKs.
///
/// The quACKs represent all packets that have ever been added to the cache,
/// including those that have already been evicted.
pub struct QuackCache {
    /// The number of bytes in the packet cache.
    #[cfg(feature = "cache_statistics")]
    pub(crate) nbytes: usize,
    /// The same length as `identifiers`.
    packet_cache: VecDeque<Packet>,
    /// The same length as `packets`.
    id_cache: VecDeque<Identifier>,
    /// The function used for calculating identifiers from packets.
    id_func: IdentifierFunc,

    quack: QuackWrapper,
    last_decode_result: Option<DecodeResult>,

    /// Cache capacity. Incoming packets >= this capacity will be handled
    /// according to the cache policy.
    capacity: usize,
    cache_policy: CachePolicy,
}

impl QuackCache {
    /// Initialize a new cache.
    pub fn new(
        riblt: bool, id_func: IdentifierFunc, quack_threshold: usize,
        capacity: usize, cache_policy: CachePolicy,
    ) -> Self {
        Self {
            #[cfg(feature = "cache_statistics")]
            nbytes: 0,
            packet_cache: VecDeque::with_capacity(capacity),
            id_cache: VecDeque::with_capacity(capacity),
            id_func,
            quack: QuackWrapper::new(quack_threshold, riblt),
            last_decode_result: None,
            cache_policy,
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
    pub fn view(&self) -> &VecDeque<Packet> {
        &self.packet_cache
    }

    /// Add a packet to the cache.
    pub fn add(&mut self, packet: Packet) -> Result<(), Packet> {
        if self.len() >= self.capacity {
            trace!("At capacity {}; dropping packet", self.capacity);
            match self.cache_policy {
                CachePolicy::SidekickReset => {
                    debug!("Reset at cache capcity={}", self.capacity);
                    return Err(packet);
                }
                CachePolicy::Optimistic => {
                    #[cfg(feature = "cache_statistics")]
                    {
                        let packet = self.packet_cache.pop_front().unwrap();
                        self.nbytes -= packet.nbytes;
                    }
                    #[cfg(not(feature = "cache_statistics"))]
                    {
                        self.packet_cache.pop_front().unwrap();
                    }
                    let id = self.id_cache.pop_front().unwrap();
                    trace!("Evicting optimistically {}", id);
                    self.quack.insert(id);
                }
            }
        }

        #[cfg(feature = "cache_statistics")]
        {
            self.nbytes += packet.nbytes;
            cache_log("add", self.nbytes);
        }

        self.id_cache.push_back(self.id_func.to_id(&packet.data));
        self.packet_cache.push_back(packet);
        Ok(())
    }

    /// Get the i-th packet (0-indexing) in the ordered cache view.
    pub fn get(&self, i: usize) -> Option<&Packet> {
        self.packet_cache.get(i)
    }

    /// Evict the recently decoded packets from the cache.
    ///
    /// The evicted packets have all been decided to be either received or
    /// lost based on the decode results of the last quACK. Eviction makes these
    /// decisions final.
    /// The `retransmit_missing` option will put the "missing" indexes at the
    /// end of the cache, as if they were just retransmitted.
    ///
    /// Returns the number of evicted packets.
    pub fn evict(&mut self, retransmit_missing: bool) -> usize {
        let last_decode_result = self.last_decode_result.take().unwrap();
        let n = last_decode_result.last_index;

        // Make received packet decisions final and evict from caches
        let ids = self.id_cache.drain(0..n).collect::<Vec<_>>();
        let packets = self.packet_cache.drain(0..n).collect::<Vec<_>>();

        // Make missing packet decisions final
        if retransmit_missing {
            for &index in &last_decode_result.missing_indexes {
                debug_assert!(index < n);
                self.quack.remove(ids[index]);
                self.add(packets[index].to_owned()).unwrap();
            }
        } else {
            for &index in &last_decode_result.missing_indexes {
                debug_assert!(index < n);
                self.quack.remove(ids[index]);
            }
        }

        // Update the number of bytes in the cache
        #[cfg(feature = "cache_statistics")]
        {
            self.nbytes =
                self.packet_cache.iter().map(|packet| packet.nbytes).sum();
            cache_log("evict", self.nbytes);
        }
        n
    }

    /// Reset the cache.
    pub fn reset(&mut self) {
        self.id_cache.clear();
        self.packet_cache.clear();
        #[cfg(feature = "cache_statistics")]
        {
            self.nbytes = 0;
            cache_log("reset", self.nbytes);
        }
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
    pub fn decode(&mut self, client_quack: &QuackWrapper) -> Result<DecodeResult, DecodeError> {
        // Check empty client quACK
        if client_quack.last_value().is_none() {
            return Err(DecodeError::EmptyClientQuack);
        }

        // Insert ids in the id cache up to the last id received by the client.
        // Assuming the client receives a subset of packets in the cache, if
        // the last value doesn't exist in our cache, then the state is
        // corrupted either by an early eviction or network packet corruption.
        cycles_start(11);
        let mut last_index = 0;
        let proxy_quack = &mut self.quack;
        for &id in &self.id_cache {
            if proxy_quack.last_value() == client_quack.last_value()
                && proxy_quack.count() >= client_quack.count() {
                break;
            }
            proxy_quack.insert(id);
            last_index += 1;
        }
        cycles_stop(11);
        if proxy_quack.last_value() != client_quack.last_value() {
            return Err(DecodeError::MissingLastValue {
                identifier: client_quack.last_value().unwrap(),
            });
        }

        // Check common case when all packets are quACKed.
        if proxy_quack.count() == client_quack.count() {
            self.last_decode_result = Some(DecodeResult {
                last_index,
                missing_indexes: vec![],
            });
            return Ok(self.last_decode_result.clone().unwrap());
        }

        // Check that we have sent more packets than were received.
        // Note that it's possible for weird behavior to occur with overflows,
        // but the state is invalid in either case.
        if proxy_quack.count() < client_quack.count() {
            return Err(DecodeError::NotASubset {
                num_recv: client_quack.count(),
                num_send: proxy_quack.count(),
                last_value: proxy_quack.last_value().unwrap(),
            });
        }

        // Check that the number of missing packets is within the threshold.
        // Fast fail for exceeded or invalid thresholds. An invalid threshold
        // is when the quacker sends less symbols than the agreed upon threshold
        // based on a hint, but estimated wrong.
        let num_missing = (proxy_quack.count() - client_quack.count()) as usize;
        if num_missing > proxy_quack.threshold() {
            return Err(DecodeError::ExceededThreshold {
                num_missing,
                threshold: proxy_quack.threshold(),
            });
        }
        let threshold = std::cmp::min(proxy_quack.threshold(), client_quack.threshold());
        if num_missing > threshold {
            return Err(DecodeError::InvalidThreshold {
                expected: proxy_quack.threshold(),
                actual: threshold,
            });
        }

        // Decode the quACK using the identifier cache.
        cycles_start(12);
        let difference_quack = proxy_quack.clone().sub(&client_quack);
        cycles_stop(12);
        cycles_start(13);
        let missing_indexes = match difference_quack {
            QuackWrapper::PowerSum(difference_quack) => {
                let coeffs = difference_quack.to_coeffs();
                self.id_cache
                    .iter()
                    .take(last_index)
                    .enumerate()
                    .filter(|(_, &id)| quack::arithmetic::eval(&coeffs, id).value() == 0)
                    .map(|(index, _)| index)
                    .collect()
            }
            QuackWrapper::IBLT(difference_quack) => {
                let missing = if let Some(missing) = difference_quack.decode() {
                    missing.into_iter().collect::<HashSet<u32>>()
                } else {
                    return Err(DecodeError::InvalidIBLT);
                };
                self.id_cache
                    .iter()
                    .take(last_index)
                    .enumerate()
                    .filter(|(_, id)| missing.contains(id))
                    .map(|(index, _)| index)
                    .collect()
            }
        };
        cycles_stop(13);
        self.last_decode_result = Some(DecodeResult { last_index, missing_indexes });
        Ok(self.last_decode_result.clone().unwrap())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DEFAULT_THRESHOLD: usize = 4;
    const DEFAULT_CAPACITY: usize = 30;

    fn new_cache() -> QuackCache {
        QuackCache::new(false, IdentifierFunc::FirstByte, DEFAULT_THRESHOLD,
                        DEFAULT_CAPACITY, CachePolicy::SidekickReset)
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

        cache.add(packet1.clone()).unwrap();
        cache.add(packet2.clone()).unwrap();

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

        cache.add(packet1.clone()).unwrap();
        cache.add(packet2.clone()).unwrap();

        assert_eq!(cache.get(0), Some(&packet1));
        assert_eq!(cache.get(1), Some(&packet2));
        assert_eq!(cache.get(2), None);
    }

    #[test]
    fn test_evict_success() {
        let mut cache = new_cache();
        cache.add(test_packet(&[1])).unwrap();
        cache.add(test_packet(&[2])).unwrap();
        cache.add(test_packet(&[3])).unwrap();

        // quack packets
        let mut q = QuackWrapper::new(DEFAULT_THRESHOLD, false);
        q.insert(1);
        q.insert(2);

        // evict partial
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 2);
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(true), 2);
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.view().len(), 1);
        assert_eq!(cache.get(0), Some(&test_packet(&[3])));

        // evict none
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 0);
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(true), 0);
        assert_eq!(cache.len(), 1);  // no change

        // evict full
        q.insert(3);
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 1);
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(true), 1);
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
        assert_eq!(cache.get(0), None);
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 0);
        assert_eq!(res.missing_indexes, vec![]);
    }

    #[test]
    fn test_reset() {
        let mut cache = new_cache();
        cache.add(test_packet(&[1])).unwrap();
        cache.reset();
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.view().len(), 0);
    }

    #[test]
    fn test_decode_none_missing() {
        let threshold = 4;
        let num_packets = 10;
        let mut q = QuackWrapper::new(threshold, false);
        let mut cache = new_cache();
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _])).unwrap();
        }

        // all packets are acked
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(true), num_packets);
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn test_decode_none_missing_prefix() {
        let threshold = 4;
        let num_packets = 10;
        let mut q = QuackWrapper::new(threshold, false);
        let mut cache = new_cache();
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _])).unwrap();
        }

        // add more packets - a strict prefix is acked
        cache.add(test_packet(&[43])).unwrap();
        cache.add(test_packet(&[27])).unwrap();
        cache.add(test_packet(&[36])).unwrap();
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![]);

        // evict some packets
        assert_eq!(cache.evict(true), num_packets);
        assert_eq!(cache.len(), 3);  // 3 new
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 0);
        assert_eq!(res.missing_indexes, vec![]);
    }

    #[test]
    fn test_decode_some_missing() {
        let num_packets = 10;
        let mut q = QuackWrapper::new(DEFAULT_THRESHOLD, false);
        let mut cache = new_cache();
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _])).unwrap();
        }

        // remove "missing" packets from the quack
        q.remove(5);
        q.remove(6);
        q.remove(8);

        // detect missing packets
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![5, 6, 8]);
        assert_eq!(cache.evict(true), num_packets);
        assert_eq!(cache.len(), 3);
    }

    #[test]
    fn test_decode_some_missing_prefix() {
        let num_packets = 10;
        let mut q = QuackWrapper::new(DEFAULT_THRESHOLD, false);
        let mut cache = new_cache();
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _])).unwrap();
        }

        // remove "missing" packets from the quack
        q.remove(5);
        q.remove(6);
        q.remove(8);

        // add more packets to the suffix - detect missing packets still
        cache.add(test_packet(&[43])).unwrap();
        cache.add(test_packet(&[27])).unwrap();
        cache.add(test_packet(&[36])).unwrap();
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, num_packets);
        assert_eq!(res.missing_indexes, vec![5, 6, 8]);

        // evict some packets
        assert_eq!(cache.evict(true), num_packets);
        assert_eq!(cache.len(), 6);  // 3 new, 3 retransmitted
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 0);
        assert_eq!(res.missing_indexes, vec![]);
    }

    #[test]
    fn test_decode_exceeded_threshold() {
        let num_packets = 10;
        let mut q = QuackWrapper::new(DEFAULT_THRESHOLD, false);
        let mut cache = new_cache();
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _])).unwrap();
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
    fn test_add_capacity_reset() {
        let mut cache = QuackCache::new(false, IdentifierFunc::FirstByte,
            DEFAULT_THRESHOLD, DEFAULT_CAPACITY, CachePolicy::SidekickReset);
        for i in 0..DEFAULT_CAPACITY as u8 {
            assert!(cache.add(test_packet(&[i])).is_ok());
        }

        assert_eq!(cache.len(), DEFAULT_CAPACITY);
        assert_eq!(cache.view().len(), DEFAULT_CAPACITY);

        // Adding the extra packet should error to cause a reset
        assert!(cache.add(test_packet(&[DEFAULT_CAPACITY as _])).is_err());
    }

    #[test]
    fn test_add_capacity_optimistic() {
        let mut cache = QuackCache::new(false, IdentifierFunc::FirstByte,
            DEFAULT_THRESHOLD, 2, CachePolicy::Optimistic);

        let packet1 = test_packet(&[1, 2, 3]);
        assert!(cache.add(packet1.clone()).is_ok());
        assert!(cache.add(packet1.clone()).is_ok());
        assert_eq!(cache.len(), 2);
        assert_eq!(cache.get(0), Some(&packet1));
        assert_eq!(cache.get(1), Some(&packet1));

        // Adding the extra packets should be successful
        let packet2 = test_packet(&[4, 5, 6]);
        println!("check 1");
        assert!(cache.add(packet2.clone()).is_ok());
        println!("check 2");
        assert!(cache.add(packet2.clone()).is_ok());
        assert_eq!(cache.len(), 2);
        assert_eq!(cache.get(0), Some(&packet2));
        assert_eq!(cache.get(1), Some(&packet2));

        // The evicted packets should be encoded in the quACK
        let mut q = QuackWrapper::new(DEFAULT_THRESHOLD, false);
        q.insert(1);
        q.insert(1);
        q.insert(4);
        q.insert(4);
        let res = cache.decode(&q).unwrap();
        assert_eq!(res.last_index, 2);
        assert_eq!(res.missing_indexes, vec![]);
    }

}
