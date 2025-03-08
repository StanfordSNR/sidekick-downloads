use quack::{Quack, PowerSumQuackU32};

/// Basic interface for a quACK sender.
///
/// The quacker quacks on the first insertion, AND if <freq_pkts> have been
/// inserted or at least <freq_ms> have elapsed since the last quack.
pub trait Quacker {
    /// Number of packets between quacks. If 0, quack frequency is only
    /// determined by <freq_ms>.
    fn freq_pkts(&self) -> u32;
    /// Number of ms elapsed between quacks. If 0, quack frequency is only
    /// determined by <freq_pkts>.
    fn freq_ms(&self) -> u64;
    /// Snapshot the quack.
    fn get_quack(&self) -> &PowerSumQuackU32;
    /// Reset the quACK.
    fn reset(&mut self);
    /// Insert an identifier into the quACK. Return whether we quack.
    fn insert(&mut self, time_ms: u64, id: u32) -> bool;
    /// Update the current time. Return whether we quACK.
    fn update_time(&mut self, time_ms: u64) -> bool;
    /// Manually quack.
    fn send_quack(&mut self, time_ms: u64);
}

#[derive(Clone)]
pub struct BaseQuacker {
    quack: PowerSumQuackU32,
    freq_pkts: u32,
    freq_ms: u64,

    last_quack_count: u32,
    last_quack_time: u64,
}

impl BaseQuacker {
    pub fn new(threshold: usize, freq_pkts: u32, freq_ms: u64) -> Self {
        Self {
            quack: PowerSumQuackU32::new(threshold),
            freq_pkts,
            freq_ms: freq_ms,
            last_quack_count: 0,
            last_quack_time: 0,
        }
    }

    pub fn threshold(&self) -> usize {
        self.quack.threshold()
    }
}

impl Quacker for BaseQuacker {
    fn freq_pkts(&self) -> u32 {
        self.freq_pkts
    }

    fn freq_ms(&self) -> u64 {
        self.freq_ms
    }

    fn get_quack(&self) -> &PowerSumQuackU32 {
        &self.quack
    }

    fn reset(&mut self) {
        self.quack = PowerSumQuackU32::new(self.quack.threshold());
        self.last_quack_count = 0;
        self.last_quack_time = 0;
    }

    fn insert(&mut self, time_ms: u64, id: u32) -> bool {
        self.quack.insert(id);
        let count = self.quack.count();
        let should_quack = count == 1 ||
            (self.freq_pkts > 0 && count >= self.last_quack_count + self.freq_pkts) ||
            (self.freq_ms > 0 && time_ms >= self.last_quack_time + self.freq_ms);
        if should_quack {
            self.send_quack(time_ms);
        }
        should_quack
    }

    fn update_time(&mut self, time_ms: u64) -> bool {
        let count = self.quack.count();
        let should_quack = count > 0 &&
            (self.freq_ms > 0 && time_ms >= self.last_quack_time + self.freq_ms);
        if should_quack {
            self.send_quack(time_ms);
        }
        should_quack
    }

    fn send_quack(&mut self, time_ms: u64) {
        self.last_quack_count = self.quack.count();
        self.last_quack_time = time_ms;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const THRESHOLD: usize = 10;
    const IDENTIFIER: u32 = 100;

    #[test]
    fn test_new_quacker() {
        let freq_pkts = 8;
        let freq_ms = 123;
        let q = BaseQuacker::new(THRESHOLD, freq_pkts, freq_ms);
        assert_eq!(q.freq_pkts(), freq_pkts);
        assert_eq!(q.freq_ms(), freq_ms);
    }

    #[test]
    fn test_quack_on_first_insert() {
        let mut q = BaseQuacker::new(THRESHOLD, 0, 0);
        assert!(q.insert(1, IDENTIFIER));
        assert!(!q.insert(2, IDENTIFIER));
        assert!(!q.insert(3, IDENTIFIER));
        assert!(!q.insert(4, IDENTIFIER));
        assert!(!q.insert(5, IDENTIFIER));
    }

    #[test]
    fn test_quack_every_packet() {
        let mut q = BaseQuacker::new(THRESHOLD, 1, 0);
        assert!(q.insert(0, IDENTIFIER));
        assert!(q.insert(0, IDENTIFIER));
        assert!(q.insert(0, IDENTIFIER));
        assert!(q.insert(0, IDENTIFIER));
        assert!(q.insert(0, IDENTIFIER));
    }

    #[test]
    fn test_quack_every_n_packets() {
        let mut q = BaseQuacker::new(THRESHOLD, 2, 0);
        assert!(q.insert(0, IDENTIFIER));
        assert!(!q.insert(0, IDENTIFIER));
        assert!(q.insert(0, IDENTIFIER));
        assert!(!q.insert(0, IDENTIFIER));
        assert!(q.insert(0, IDENTIFIER));
    }

    #[test]
    fn test_quack_every_n_ms_on_insert() {
        let mut q = BaseQuacker::new(THRESHOLD, 0, 2);
        assert!(q.insert(0, IDENTIFIER));
        assert!(!q.insert(0, IDENTIFIER));
        assert!(!q.insert(1, IDENTIFIER));
        assert!(q.insert(2, IDENTIFIER));
        assert!(q.insert(4, IDENTIFIER));
        assert!(!q.insert(5, IDENTIFIER));
        assert!(q.insert(10, IDENTIFIER));
        assert!(!q.insert(11, IDENTIFIER));
    }

    #[test]
    fn test_quack_every_n_ms_without_insert() {
        let mut q = BaseQuacker::new(THRESHOLD, 0, 5);
        assert!(!q.update_time(10));
        assert!(!q.update_time(20));
        assert!(q.insert(30, IDENTIFIER));
        assert!(!q.update_time(31));
        assert!(!q.update_time(34));
        assert!(q.update_time(35));
        assert!(!q.update_time(35));
        assert!(!q.update_time(39));
        assert!(q.update_time(100));
    }

    #[test]
    fn test_quack_with_both_frequencies() {
        let mut q = BaseQuacker::new(THRESHOLD, 5, 10);
        assert!(q.insert(0, IDENTIFIER));
        assert!(q.insert(10, IDENTIFIER));
        assert!(q.insert(25, IDENTIFIER));
        assert!(!q.insert(30, IDENTIFIER));
        assert!(!q.insert(31, IDENTIFIER));
        assert!(!q.insert(32, IDENTIFIER));
        assert!(!q.insert(33, IDENTIFIER));
        assert!(q.insert(34, IDENTIFIER));
        assert!(!q.insert(40, IDENTIFIER));
    }

    #[test]
    fn test_quack_reset() {
        let mut q = BaseQuacker::new(THRESHOLD, 0, 0);
        assert!(q.insert(1, IDENTIFIER));
        assert!(!q.insert(2, IDENTIFIER));
        assert!(!q.insert(3, IDENTIFIER));
        q.reset();
        assert!(q.insert(4, IDENTIFIER));
        assert!(!q.insert(5, IDENTIFIER));
    }

    #[test]
    fn test_quack_manual_send() {
        let mut q = BaseQuacker::new(THRESHOLD, 0, 0);
        assert!(q.insert(1, IDENTIFIER));
        assert!(!q.insert(2, IDENTIFIER));
        assert!(!q.insert(3, IDENTIFIER));
        q.send_quack(4);
        assert!(!q.insert(5, IDENTIFIER));
        assert!(!q.update_time(6));
    }
}