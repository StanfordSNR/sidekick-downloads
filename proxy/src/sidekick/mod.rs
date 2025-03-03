mod base;

pub use base::Sidekick;

/// Identifies the connection as base or sidekick
pub enum ConnectionType {
    /// Base connection from client to server
    BaseCtos,
    /// Base connection from server to client
    BaseStoc,
    /// Sidekick connection
    Sidekick,
    /// Sidekick configuration packet
    Discovery,
    /// Some other connection (forward only)
    None
}
