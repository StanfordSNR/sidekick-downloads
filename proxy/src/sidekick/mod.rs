mod base;
mod multicast;

pub use base::Sidekick;
pub use multicast::SidekickMulticast;

use sidekick_utils::buffer::AddrKey;

/// Identifies the connection as base or sidekick
pub enum ConnectionType {
    /// Base connection from server to client
    BaseStoc { base_conn: AddrKey, sidekick_conn: AddrKey },
    /// Sidekick connection
    Sidekick { sidekick_conn: AddrKey },
    /// Sidekick configuration packet
    Discovery,
    /// Some other connection (forward only)
    None
}
