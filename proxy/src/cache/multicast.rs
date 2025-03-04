use std::collections::HashMap;
use std::cmp::min;

use log::{trace, error};
use sidekick_utils::buffer::AddrKey;
use sidekick_utils::identifier::{Identifier, IdentifierFunc};
use quack::{arithmetic::ModularArithmetic, PowerSumQuack, PowerSumQuackU32};

use crate::stream::Packet;
use crate::cache::{DecodeError, DecodeResult};


/// Requires the insertion indexes in insertions >= next.
/// The indexes that are being inserted must be < the insertion index.
#[derive(Debug)]
struct VirtualBuffer {
    // The first received index in the base buffer
    _start: usize,
    // *One after* the last received index in the base buffer
    // (the next index to receive)
    next: usize,
    // The first value is at which index in the base buffer to insert.
    // The second value is the index in the base buffer of the inserted id.
    // The insertion indexes are in sorted order.
    insertions: Vec<(usize, usize)>,
}

impl VirtualBuffer {
    fn new(start: usize) -> Self {
        Self {
            _start: start,
            next: start,
            insertions: Vec::new(),
        }
    }
}

/// Per-sidekick connection state in the multicast cache.
#[derive(Debug)]
struct ConnState {
    quack: PowerSumQuackU32,
    buffer: VirtualBuffer,
}

impl ConnState {
    fn new(quack: PowerSumQuackU32, start: usize) -> Self {
        Self {
            quack,
            buffer: VirtualBuffer::new(start),
        }
    }
}

/// A cache of packets that is able to decode quACKs.
///
/// The quACKs represent all packets that have ever been added to the cache,
/// including those that have already been evicted.
pub struct QuackCacheMulticast {
    /// Number of evicted packets previously in the cache
    num_evicted: usize,
    /// The same length as `identifiers`.
    packet_cache: Vec<Packet>,
    /// The same length as `packets`.
    id_cache: Vec<Identifier>,
    /// The function used for calculating identifiers from packets.
    id_func: IdentifierFunc,
    /// Cache capacity. Incoming packets >= this capacity will be dropped.
    capacity: usize,
    /// QuACK threshold
    threshold: usize,
    /// Per-connection state
    conns: HashMap<AddrKey, ConnState>,
}

impl QuackCacheMulticast {
    /// Initialize a new multicast cache.
    pub fn new(id_func: IdentifierFunc, quack_threshold: usize, capacity: usize) -> Self {
        Self {
            num_evicted: 0,
            packet_cache: vec![],
            id_cache: vec![],
            id_func,
            capacity,
            threshold: quack_threshold,
            conns: HashMap::new(),
        }
    }

    /// Initialize a new sidekick connection subscribed to this multicast
    /// base connection.
    pub fn init_conn(&mut self, conn: &AddrKey) {
        let start = self.total();
        let quack = PowerSumQuackU32::new(self.threshold);
        self.conns.insert(*conn, ConnState::new(quack, start));
    }

    /// The number of packets currently in the cache.
    pub fn len(&self) -> usize {
        debug_assert!(self.packet_cache.len() <= self.capacity);
        debug_assert!(self.packet_cache.len() == self.id_cache.len());
        self.packet_cache.len()
    }

    /// The total number of packets that have ever been in the cache, including
    /// those that were evicted.
    pub fn total(&self) -> usize {
        self.num_evicted + self.len()
    }

    /// Return a read-only view of packets in the cache that have not been
    /// evicted, ordered from least to most recently added.
    pub fn view(&self) -> &[Packet] {
        self.packet_cache.as_slice()
    }

    /// Return the identifiers of the read-only view of packets in the cache
    /// that have not been evicted, as returned by `view()`.
    pub fn view_ids(&self) -> &[u32] {
        self.id_cache.as_slice()
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

    /// Get the i-th packet (0-indexing) in the cache, including those that
    /// were evicted.
    pub fn get(&self, i: usize) -> Option<&Packet> {
        if i >= self.num_evicted {
            self.packet_cache.get(i - self.num_evicted)
        } else {
            error!("tried to get evicted packet index={}", i);
            None
        }
    }

    /// Get the i-th packet identifier (0-indexing) in the cache, including
    /// those that were evicted.
    pub fn get_id(&self, i: usize) -> Option<u32> {
        if i >= self.num_evicted {
            self.id_cache.get(i - self.num_evicted).copied()
        } else {
            error!("tried to get evicted packet index={}", i);
            None
        }
    }

    /// Evict the recently decoded packets from the cache.
    ///
    /// Since the packets are shared by multiple connections, only evict the
    /// packets that have been decided to be *received* based on the decode
    /// results of *all* subscribed connections.
    ///
    /// Note that packets that have been decided to be lost stay in the cache
    /// until they are ultimately retransmitted. Since we can only evict a
    /// prefix packets, and the packets awaiting retransmission to individual
    /// clients are not reordered in the base cache, packets with an index
    /// *greater* than that of the lost packet will stick around until it is
    /// quACKed. The connection may be reset if it falls too far behind.
    ///
    /// Returns the number of evicted packets.
    pub fn evict(&mut self) -> usize {
        // Find the number of packets to evict.
        // All of the packets have been received by all current connections.
        let n = {
            let mut n = self.total();
            for buffer in self.conns.values().map(|state| &state.buffer) {
                n = min(n, buffer.next);
                n = min(n, buffer.insertions.iter().map(|(_, idx)| *idx)
                                            .min().unwrap_or(n));
            }
            n - self.num_evicted
        };

        // Remove these packets from the cache
        self.id_cache.drain(0..n);
        self.packet_cache.drain(0..n);
        self.num_evicted += n;
        n
    }

    /// Reset the state for this connection.
    pub fn reset(&mut self, conn: &AddrKey) {
        self.init_conn(conn);
    }

    /// Given a quACK from the client, determines which packets the proxy has
    /// sent have been definitively received or likely lost.
    ///
    /// The quACK for each connection is the cumulative representation of all
    /// packets that have ever been added to the cache that the client in that
    /// connection has actually received, including those that have already
    /// been evicted.
    ///
    /// Assumes the proxy immediately retransmits the likely lost packets, and
    /// reorders the internal buffer for this connection accordingly. If the
    /// connection enters an invalid state, the cache relies on reset packets
    /// to make the state consistent again.
    ///
    /// Returns an error if the quACK fails to decode.
    pub fn decode(
        &mut self, client_quack: &PowerSumQuackU32, conn: &AddrKey,
    ) -> Result<DecodeResult, DecodeError> {
        // Check empty client quACK
        if client_quack.last_value().is_none() {
            return Err(DecodeError::EmptyClientQuack);
        }

        // Check invalid threshold
        if self.threshold != client_quack.threshold() {
            return Err(DecodeError::InvalidThreshold {
                expected: self.threshold,
                actual: client_quack.threshold(),
            });
        }

        // Get the state for this connection.
        let state = self.conns.get_mut(conn).unwrap();

        /*
        // Insert ids in the id cache up to the last id received by the client.
        // Assuming the client receives a subset of packets in the cache, if
        // the last value doesn't exist in our cache, then the state is
        // corrupted either by an early eviction or network packet corruption.
        let mut last_index = 0;
        let mut proxy_quack = proxy_quack.clone();
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

        // Check that we have sent more packets than were received.
        if proxy_quack.count() < client_quack.count() {
            return Err(DecodeError::NotASubset {
                num_recv: client_quack.count(),
                num_send: proxy_quack.count(),
                last_value: proxy_quack.last_value().unwrap(),
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
        Ok(result)
        */
        unimplemented!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DEFAULT_THRESHOLD: usize = 4;
    const DEFAULT_CAPACITY: usize = 30;
    const CONN1: AddrKey = [1u8; 12];
    const CONN2: AddrKey = [2u8; 12];
    const CONN3: AddrKey = [3u8; 12];

    fn new_cache() -> QuackCacheMulticast {
        QuackCacheMulticast::new(
            IdentifierFunc::FirstByte, DEFAULT_THRESHOLD, DEFAULT_CAPACITY)
    }

    fn test_packet_view(ids: &[u8]) -> Vec<Packet> {
        ids.iter().map(|&id| test_packet(&[id])).collect::<Vec<_>>()
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
        assert_eq!(cache.total(), 0);
        assert_eq!(cache.view(), &[]);
        assert_eq!(cache.view_ids(), &[]);
        assert_eq!(cache.get(0), None);
    }

    #[test]
    fn test_add_two_packets() {
        let mut cache = new_cache();
        let packet1 = test_packet(&[1, 2, 3]);
        let packet2 = test_packet(&[4, 5, 6]);

        cache.add(packet1.clone());
        cache.add(packet2.clone());

        assert_eq!(cache.len(), 2);
        assert_eq!(cache.total(), 2);
        assert_eq!(cache.view(), &[packet1.clone(), packet2.clone()]);
        assert_eq!(cache.view_ids(), &[1, 4]);
        assert_eq!(cache.get(0), Some(&packet1));
        assert_eq!(cache.get(1), Some(&packet2));
        assert_eq!(cache.get(2), None);

        assert_eq!(cache.evict(), 2);
        assert_eq!(cache.len(), 0);
        assert_eq!(cache.total(), 2);
        assert_eq!(cache.view(), &[]);
        assert_eq!(cache.view_ids(), &[]);
        assert_eq!(cache.get(0), None);
    }

    #[test]
    fn test_add_capacity() {
        let mut cache = new_cache();
        for i in 0..DEFAULT_CAPACITY as u8 {
            cache.add(test_packet(&[i]));
        }

        assert_eq!(cache.total(), DEFAULT_CAPACITY);
        assert_eq!(cache.len(), DEFAULT_CAPACITY);

        // Adding the extra packet should have no impact
        cache.add(test_packet(&[DEFAULT_CAPACITY as _]));
        assert_eq!(cache.total(), DEFAULT_CAPACITY);
        assert_eq!(cache.len(), DEFAULT_CAPACITY);
    }

    #[test]
    fn test_decode_none_missing_from_start() {
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();

        // connection joins at the start
        cache.init_conn(&CONN1);
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }
        assert_eq!(cache.len(), num_packets);

        // all packets are acked
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), num_packets);
        assert_eq!(cache.len(), 0);

        // add more packets - a strict prefix is acked
        q.insert(43);
        cache.add(test_packet(&[43]));
        cache.add(test_packet(&[27]));
        cache.add(test_packet(&[36]));
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), 1);
        assert_eq!(cache.len(), 2);

        // decode the same quack twice in a row
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.len(), 2);
    }

    #[test]
    fn test_decode_none_missing_from_middle() {
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();
        cache.add(test_packet(&[0]));
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));

        // connection joins at the start
        cache.init_conn(&CONN1);
        for i in 3..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }
        assert_eq!(cache.len(), num_packets);

        // all packets are acked
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), num_packets);
        assert_eq!(cache.len(), 0);

        // add more packets - a strict prefix is acked
        q.insert(43);
        cache.add(test_packet(&[43]));
        cache.add(test_packet(&[27]));
        cache.add(test_packet(&[36]));
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), 1);
        assert_eq!(cache.len(), 2);

        // decode the same quack twice in a row
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.len(), 2);
    }

    #[test]
    fn test_decode_some_missing_from_start() {
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();

        // connection joins at the start
        cache.init_conn(&CONN1);
        for i in 0..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }

        // remove "missing" packets from the quack
        q.remove(5);
        q.remove(6);
        q.remove(8);

        // detect missing packets
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![5, 6, 8]);
        assert_eq!(cache.evict(), 5);
        assert_eq!(cache.len(), 5);

        // missing packets are considered retransmitted
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), 0);
        assert_eq!(cache.len(), 5);

        // add more packets to the suffix - retxed packets are now missing
        q.insert(5);
        q.insert(11);
        cache.add(test_packet(&[10]));
        cache.add(test_packet(&[11]));
        cache.add(test_packet(&[12]));
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![6, 8, 10]);
        assert_eq!(cache.evict(), 1);
        assert_eq!(cache.len(), 7);
    }

    #[test]
    fn test_decode_some_missing_from_middle() {
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();
        cache.add(test_packet(&[0]));
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));

        // connection joins in the middle
        cache.init_conn(&CONN1);
        for i in 3..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }

        // remove "missing" packets from the quack
        q.remove(5);
        q.remove(6);
        q.remove(8);

        // detect missing packets
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![5, 6, 8]);
        assert_eq!(cache.evict(), 5);
        assert_eq!(cache.len(), 5);

        // missing packets are considered retransmitted
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), 0);
        assert_eq!(cache.len(), 5);

        // add more packets to the suffix - retxed packets are now missing
        q.insert(5);
        q.insert(11);
        cache.add(test_packet(&[10]));
        cache.add(test_packet(&[11]));
        cache.add(test_packet(&[12]));
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![6, 8, 10]);
        assert_eq!(cache.evict(), 1);
        assert_eq!(cache.len(), 7);
    }

    #[test]
    fn test_get_missing_packets() {
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();
        cache.add(test_packet(&[0]));

        // connection joins midway
        cache.init_conn(&CONN1);
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));
        cache.add(test_packet(&[3]));
        cache.add(test_packet(&[4]));

        // decode a quack with a missing packet
        q.insert(1);
        q.insert(3);
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![2]);
        assert_eq!(cache.evict(), 2);

        // lose a packet after this eviction
        cache.add(test_packet(&[5]));
        q.insert(5);
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![4, 2]);
        assert_eq!(cache.evict(), 0);

        // can we get these packets?
        assert_eq!(cache.get(4), Some(&test_packet(&[4])));
        assert_eq!(cache.get(2), Some(&test_packet(&[2])));
    }

    #[test]
    fn test_decode_exceeded_threshold() {
        let num_packets = 10;
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let mut cache = new_cache();
        cache.add(test_packet(&[100]));
        cache.add(test_packet(&[110]));
        cache.add(test_packet(&[120]));

        // connection joins midway
        cache.init_conn(&CONN1);
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
        let res = cache.decode(&q, &CONN1);
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
    fn test_reset_none_missing() {
        let mut cache = new_cache();
        cache.add(test_packet(&[0]));

        // connection joins midway
        cache.init_conn(&CONN1);

        // send a packet before resetting the connection
        cache.add(test_packet(&[1]));
        cache.reset(&CONN1);

        // it's as if the connection joined at a later midway point
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        let num_packets = 10;
        for i in 2..num_packets {
            q.insert(i as _);
            cache.add(test_packet(&[i as _]));
        }
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
    }

    #[test]
    fn test_reset_with_missing_packets() {
        let mut cache = new_cache();
        cache.add(test_packet(&[0]));

        // connection joins midway
        cache.init_conn(&CONN1);
        cache.add(test_packet(&[1]));
        cache.add(test_packet(&[2]));
        cache.add(test_packet(&[3]));
        assert_eq!(cache.len(), 4);

        // create a quack with missing packets
        let mut q = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        q.insert(1);
        q.insert(3);

        // decode and evict
        let res = cache.decode(&q, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![2]);
        assert_eq!(cache.evict(), 2);
        assert_eq!(cache.len(), 2);

        // reset and evict
        cache.reset(&CONN1);
        assert_eq!(cache.evict(), 2);
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn test_multiple_conns() {
        let mut cache = new_cache();
        cache.add(test_packet(&[0]));
        cache.add(test_packet(&[1]));

        cache.init_conn(&CONN2);
        cache.init_conn(&CONN3);
        cache.add(test_packet(&[2]));

        cache.init_conn(&CONN1);
        cache.add(test_packet(&[3]));
        cache.add(test_packet(&[4]));
        cache.add(test_packet(&[5]));
        cache.add(test_packet(&[6]));
        cache.add(test_packet(&[7]));

        let mut q1 = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        q1.insert(3);
        q1.insert(6);
        let mut q2 = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        q2.insert(2);
        q2.insert(3);
        q2.insert(5);
        let mut q3 = PowerSumQuackU32::new(DEFAULT_THRESHOLD);
        q3.insert(2);
        q3.insert(3);
        q3.insert(4);
        q3.insert(5);
        q3.insert(6);

        assert_eq!(cache.view(), test_packet_view(&[0, 1, 2, 3, 4, 5, 6, 7]));
        let res = cache.decode(&q1, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![4, 5]);
        assert_eq!(cache.evict(), 2);

        assert_eq!(cache.view(), test_packet_view(&[2, 3, 4, 5, 6, 7]));
        let res = cache.decode(&q2, &CONN2).unwrap();
        assert_eq!(res.missing_indexes, vec![4]);
        assert_eq!(cache.evict(), 0);

        assert_eq!(cache.view(), test_packet_view(&[2, 3, 4, 5, 6, 7]));
        let res = cache.decode(&q3, &CONN3).unwrap();
        assert_eq!(res.missing_indexes, vec![]);
        assert_eq!(cache.evict(), 2);

        cache.add(test_packet(&[8]));
        q1.insert(8);
        q2.insert(8);
        q3.insert(8);

        assert_eq!(cache.view(), test_packet_view(&[4, 5, 6, 7, 8]));
        let res = cache.decode(&q1, &CONN1).unwrap();
        assert_eq!(res.missing_indexes, vec![7, 4, 5]);
        let res = cache.decode(&q2, &CONN2).unwrap();
        assert_eq!(res.missing_indexes, vec![6, 7, 4]);
        let res = cache.decode(&q3, &CONN3).unwrap();
        assert_eq!(res.missing_indexes, vec![7]);
        assert_eq!(cache.evict(), 0);
    }
}
