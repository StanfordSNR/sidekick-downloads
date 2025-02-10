pub mod socket;
pub use socket::{Socket, SockAddr};

pub mod identifier;
pub use identifier::{IdentifierFunc, Identifier};

pub mod buffer;
pub use buffer::{AddrKey, UdpParser};

pub const ID_OFFSET: usize = 63;
pub const DEFAULT_MTU: usize = 1500;

// Ethernet (14), IP (20), TCP/UDP (8) headers
// The randomly-encrypted payload in a QUIC packet with a short header is at
// offset 63.
#[cfg(feature = "client")]
pub const BUFFER_SIZE: usize = ID_OFFSET + 4;


// Proxy must be able to receive and forward complete packets
#[cfg(not(feature = "client"))]
pub const BUFFER_SIZE: usize = (DEFAULT_MTU + 14 + 8).next_power_of_two();