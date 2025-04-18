#[cfg(feature = "ack64")]
pub const BLOCK_SIZE: u32 = 64;
#[cfg(not(feature = "ack64"))]
pub const BLOCK_SIZE: u32 = 32;

/// Example:
///
/// seqno = 101
/// block = 11001000 00000000 00000000 00000001
/// 0-68 may or may not have been received. 69, 96, 99, 100 have been received.
/// 101+ and the remaining packets from 70-99 have not been received.
///
/// seqno = 32
/// block = 00001000 00000000 00000000 00000001
/// 0, 27 have been received. 1-26, 28+ have not been received.
///
/// seqno must be at least the block size.
#[derive(Debug, Clone, Copy)]
pub struct BlockAck {
    /// Seqno of 1 + the most significant bit in the block.
    /// If the seqno is greater than the block size, it is equal to one more
    /// than the largest acknowledged packet.
    pub seqno: u32,
    /// Default is BLOCK_SIZE packets
    #[cfg(feature = "ack64")]
    pub block: u64,
    #[cfg(not(feature = "ack64"))]
    pub block: u32,
}

impl BlockAck {
    pub fn new() -> Self {
        Self {
            seqno: BLOCK_SIZE,
            block: 0,
        }
    }

    /// Returns whether the seqno is a new one. Returns None if it is below
    /// the range.
    pub fn ack(&mut self, seqno: u32) -> Option<bool> {
        // Below the block range, doesn't matter anymore
        if seqno + BLOCK_SIZE < self.seqno {
            None
        }
        // Within the block range
        else if seqno < self.seqno {
            let min_seqno = self.seqno - BLOCK_SIZE;
            let num_to_shift = seqno - min_seqno;
            let mask = 1 << num_to_shift;
            if self.block & mask == 0 {
                self.block |= mask;
                Some(true)
            } else {
                Some(false)
            }
        }
        // Above the block range
        else {
            if seqno - self.seqno >= BLOCK_SIZE {
                self.block = 1 << (BLOCK_SIZE - 1);
            } else {
                let num_to_shift = seqno - self.seqno + 1;
                self.block >>= num_to_shift;
                self.block |= 1 << (BLOCK_SIZE - 1);
            }
            self.seqno = seqno + 1;
            Some(true)
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_ack_within_range() {
        let mut ack = BlockAck::new();
        assert!(ack.ack(0).unwrap());
        assert_eq!(ack.seqno, 32);
        assert_eq!(ack.block, 1);
        assert!(ack.ack(1).unwrap());
        assert_eq!(ack.seqno, 32);
        assert_eq!(ack.block, 1 | (1 << 1));
        assert!(ack.ack(31).unwrap());
        assert_eq!(ack.seqno, 32);
        assert_eq!(ack.block, 1 | (1 << 1) | (1 << 31));
    }

    #[test]
    fn test_ack_above_range() {
        let mut ack = BlockAck::new();
        assert!(ack.ack(0).unwrap());
        assert_eq!(ack.seqno, 32);
        assert_eq!(ack.block, 1);
        assert!(ack.ack(32).unwrap());
        assert_eq!(ack.seqno, 33);
        assert_eq!(ack.block, 1 << 31);
        assert!(ack.ack(34).unwrap());
        assert_eq!(ack.seqno, 35);
        assert_eq!(ack.block, (1 << 31) | (1 << 29));
    }

    #[test]
    fn test_ack_below_range() {
        let mut ack = BlockAck::new();
        assert!(ack.ack(32).unwrap());
        assert_eq!(ack.seqno, 33);
        assert_eq!(ack.block, 1 << 31);
        assert!(ack.ack(0).is_none());
        assert_eq!(ack.seqno, 33);
        assert_eq!(ack.block, 1 << 31);
    }

    #[test]
    fn test_new_and_old_acks() {
        let mut ack = BlockAck::new();
        assert!(ack.ack(0).unwrap());
        assert!(ack.ack(64).unwrap());
        assert!(!ack.ack(64).unwrap());
        assert!(ack.ack(0).is_none());
    }
}
