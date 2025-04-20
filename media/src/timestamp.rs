use tokio::time::{Duration, Instant};

pub struct AudioTimestamper {
    first_seqno: u32,
    first_time: Instant,
    frequency: Duration,
}

impl AudioTimestamper {
    /// One packet is generated every `frequency`, starting at `time_init` with
    /// the seqno `first_seqno`.
    pub fn new(
        first_seqno: u32, first_time: Instant, frequency: Duration,
    ) -> Self {
        Self {
            first_seqno,
            first_time,
            frequency,
        }
    }

    pub fn ts(&self, seqno: u32) -> Instant {
        let num_seqnos = seqno - self.first_seqno;
        self.first_time + num_seqnos * self.frequency
    }
}
