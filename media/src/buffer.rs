use std::collections::VecDeque;
use tokio::time::{Duration, Instant};

#[derive(Debug, PartialEq, Eq, PartialOrd, Ord)]
struct Seqno {
    seqno: u32,
    time_recv: Option<Instant>,
    time_lost: Option<Instant>,
    time_nack: Option<Instant>,
}

impl Seqno {
    fn new(seqno: u32) -> Self {
        Self {
            seqno,
            time_recv: None,
            time_lost: None,
            time_nack: None,
        }
    }
}

#[derive(Debug, Copy, Clone)]
pub struct PlayResult {
    /// Seqno of the packet that is played
    pub seqno: u32,
    /// Time when the packet was first received
    pub time_recv: Instant,
}

pub struct BufferedPackets {
    first_seqno: u32,
    /// Next seqno to play, and the seqno of the first packet in the buffer
    /// if the buffer is non-empty.
    next_seqno: u32,
    buffer: VecDeque<Seqno>,
}

impl BufferedPackets {
    pub fn new(first_seqno: u32) -> Self {
        Self {
            first_seqno,
            next_seqno: first_seqno,
            buffer: VecDeque::new(),
        }
    }

    /// Receive a packet with this sequence number.
    ///
    /// Returns whether the seqno was already received and is in the range of
    /// seqnos we expect to receive.
    pub fn recv_seqno(&mut self, new_seqno: u32, now: Instant) -> bool {
        // Ignore the seqno if it has already been received.
        if new_seqno < self.next_seqno {
            return new_seqno >= self.first_seqno;
        }

        // Add packets to the buffer until the seqno is guaranteed to be there.
        if self.buffer.is_empty() {
            self.buffer.push_back(Seqno::new(self.next_seqno));
        }
        let next_seqno_to_push = self.buffer.back().unwrap().seqno + 1;
        for seqno in next_seqno_to_push..(new_seqno + 1) {
            self.buffer.push_back(Seqno::new(seqno));
        }

        // Go through the buffer and mark the new packet received.
        for packet in self.buffer.iter_mut() {
            if packet.seqno == new_seqno {
                if packet.time_recv.is_none() {
                    packet.time_recv = Some(now);
                    packet.time_lost = None;
                    packet.time_nack = None;
                    return false;
                } else {
                    return true;
                }
            }
        }

        // Seqno should have been marked received.
        unreachable!()
    }

    /// Return the received time of the next packet to play if the next packet
    /// in the sequence is available. Removes that packet from the buffer.
    pub fn pop_seqno(&mut self) -> Option<PlayResult> {
        if !self.buffer.is_empty() && self.buffer.front().unwrap().time_recv.is_some() {
            let packet = self.buffer.pop_front().unwrap();
            self.next_seqno += 1;
            Some(PlayResult {
                seqno: packet.seqno,
                time_recv: packet.time_recv.unwrap(),
            })
        } else {
            None
        }
    }

    /// Returns a list of seqnos to NACK, and marks them as NACKed.
    ///
    /// NACKs a seqno if there is a "hole", as in there is a larger seqno that
    /// was received than the missing seqno. Also NACKs if it has been more
    /// than <nack_frequency> since a missing seqno was last NACKed. If there
    /// is a NACK delay, doesn't NACK the packet until it has been lost for at
    /// least that length of time.
    ///
    /// Also returns if any packets are missing even if there are no NACKs to
    /// send.
    pub fn nacks_to_send(
        &mut self, now: Instant, nack_frequency: Duration,
        nack_delay: Option<Duration>,
    ) -> (Vec<u32>, usize) {
        let mut nacks = vec![];
        let mut num_missing = 0;
        if self.buffer.is_empty() {
            return (nacks, num_missing);
        }
        for packet in self.buffer.iter_mut() {
            if packet.time_recv.is_some() {
                continue;
            }
            if packet.time_lost.is_none() {
                packet.time_lost = Some(now);
            }
            num_missing += 1;
            if let Some(nack_delay) = nack_delay {
                if now < packet.time_lost.unwrap() + nack_delay {
                    continue;
                }
            }
            if let Some(time_nack) = packet.time_nack.as_mut() {
                if now - *time_nack > nack_frequency {
                    nacks.push(packet.seqno);
                    *time_nack = now;
                }
            } else {
                nacks.push(packet.seqno);
                packet.time_nack = Some(now);
            }
        }
        (nacks, num_missing)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pop_consecutive_seqno() {
        let mut buffer = BufferedPackets::new(1);
        let now = Instant::now();
        buffer.recv_seqno(1, now);
        buffer.recv_seqno(2, now);
        buffer.recv_seqno(3, now);
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_none());
    }

    #[test]
    fn test_new_with_first_seqno() {
        let mut buffer = BufferedPackets::new(10);
        let now = Instant::now();
        assert!(!buffer.recv_seqno(9, now));
        assert!(!buffer.recv_seqno(10, now));
        assert!(!buffer.recv_seqno(12, now));
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_none());
        assert!(!buffer.recv_seqno(11, now));
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_none());
    }

    #[test]
    fn test_pop_missing_seqno() {
        let mut buffer = BufferedPackets::new(1);
        let now = Instant::now();
        buffer.recv_seqno(2, now);
        buffer.recv_seqno(3, now);
        buffer.recv_seqno(5, now);
        assert!(buffer.pop_seqno().is_none());
        buffer.recv_seqno(1, now);
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_none());
        buffer.recv_seqno(6, now);
        assert!(buffer.pop_seqno().is_none());
        buffer.recv_seqno(4, now);
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_some());
        assert!(buffer.pop_seqno().is_none());
    }

    #[test]
    fn test_recv_seqno() {
        let mut buffer = BufferedPackets::new(1);
        let now = Instant::now();
        assert!(!buffer.recv_seqno(1, now));
        assert!(buffer.recv_seqno(1, now));
        assert!(!buffer.recv_seqno(3, now));
        assert!(!buffer.recv_seqno(4, now));
        assert!(!buffer.recv_seqno(5, now));
        assert!(buffer.recv_seqno(3, now));
        assert!(buffer.recv_seqno(4, now));
        assert!(buffer.recv_seqno(5, now));
        assert!(!buffer.recv_seqno(2, now));
        assert!(buffer.recv_seqno(2, now));
    }

    #[test]
    fn test_nacks_to_send() {
        let mut buffer = BufferedPackets::new(1);
        let now = Instant::now();
        let freq = Duration::from_millis(10);

        // nothing missing to start
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, None);
        assert_eq!(nacks.len(), 0);
        assert_eq!(num_missing, 0);

        // receive some packets
        buffer.recv_seqno(2, now);
        buffer.recv_seqno(3, now);
        buffer.recv_seqno(5, now);

        // nack the holes
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, None);
        assert_eq!(nacks.len(), 2);
        assert_eq!(nacks[0], 1);
        assert_eq!(nacks[1], 4);
        assert_eq!(num_missing, 2);

        // nacked too soon after
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, None);
        assert_eq!(nacks.len(), 0);
        assert_eq!(num_missing, 2);

        // nack after freq time has elapsed
        let now = now + freq + Duration::from_millis(1);
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, None);
        assert_eq!(nacks.len(), 2);
        assert_eq!(nacks[0], 1);
        assert_eq!(nacks[1], 4);
        assert_eq!(num_missing, 2);
    }

    #[test]
    fn test_nacks_to_send_with_delay() {
        let mut buffer = BufferedPackets::new(1);
        let now = Instant::now();
        let freq = Duration::from_millis(10);
        let delay = Duration::from_millis(30);
        buffer.recv_seqno(2, now);
        buffer.recv_seqno(3, now);
        buffer.recv_seqno(5, now);

        // too soon to nack
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, Some(delay));
        assert_eq!(nacks.len(), 0);
        assert_eq!(num_missing, 2);

        // still too soon to nack
        let now = now + delay - Duration::from_millis(1);
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, Some(delay));
        assert_eq!(nacks.len(), 0);
        assert_eq!(num_missing, 2);

        // we can nack now
        let now = now + Duration::from_millis(2);
        let (nacks, num_missing) = buffer.nacks_to_send(now, freq, Some(delay));
        assert_eq!(nacks.len(), 2);
        assert_eq!(nacks[0], 1);
        assert_eq!(nacks[1], 4);
        assert_eq!(num_missing, 2);
    }
}
