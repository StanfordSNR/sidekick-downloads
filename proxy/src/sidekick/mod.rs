mod base;
mod multicast;

pub use base::Sidekick;
pub use multicast::SidekickMulticast;

use sidekick_utils::buffer::AddrKey;

/// Identifies the connection as base or sidekick
pub enum ConnectionType {
    /// Base connection from client to server
    BaseCtos,
    /// Base connection from server to client
    BaseStoc,
    /// Sidekick connection
    Sidekick(AddrKey),
    /// Sidekick configuration packet
    Discovery,
    /// Some other connection (forward only)
    None
}
