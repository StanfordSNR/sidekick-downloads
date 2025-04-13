mod base;
mod multicast;

pub use base::Sidekick;
pub use multicast::SidekickMulticast;

use sidekick_utils::buffer::AddrKey;

/// Identifies the type of connection the received packet belongs to
pub enum ConnectionType {
    /// Base connection from server to client
    BaseStoc { sidekick_conn: AddrKey },
    /// Sidekick connection
    Sidekick { sidekick_conn: AddrKey },
    /// Some other connection (forward only)
    None
}
