use sidekick_utils::{ID_OFFSET, UDP_PAYLOAD_OFFSET};

mod statistics;
mod buffer;
mod packet;

pub const PAYLOAD_SIZE: usize = 240;
pub const PAYLOAD_ID_OFFSET: usize = ID_OFFSET - UDP_PAYLOAD_OFFSET;
pub const NACK_PAYLOAD_SIZE: usize = PAYLOAD_ID_OFFSET + 4;
pub const INITIAL_SEQNO: u32 = 0;
pub const TIMEOUT_SEQNO: u32 = u32::MAX;

pub use statistics::Statistics;
pub use buffer::BufferedPackets;
pub use packet::Packet;
