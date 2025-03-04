pub mod socket;
pub mod identifier;
pub mod buffer;
pub mod packet;

pub const ID_OFFSET: usize = 63;
pub const UDP_PAYLOAD_OFFSET: usize = 42;
pub const DEFAULT_MTU: usize = 1500;

// Ethernet (14), IP (20), TCP/UDP (8) headers = 42.
// The randomly-encrypted payload in a QUIC packet with a short header is at
// offset 63. Buffer size used if only interested in parsing the identifier.
// Note that sidekick payloads must also be less than this buffer size. This
// is true except for the retransmit payload, at the moment.
pub const ID_BUFFER_SIZE: usize = ID_OFFSET + 4;

// Proxy must be able to receive and forward complete packets
pub const BUFFER_SIZE: usize = (DEFAULT_MTU + 14 + 8).next_power_of_two();

#[macro_export]
macro_rules! fmt_hex {
    ($hex:expr) => {
        $hex.iter().map(|b| format!("{:02x}", b)).collect::<String>()
    };
}

mod ffi;