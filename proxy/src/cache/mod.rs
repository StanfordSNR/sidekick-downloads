mod base;
mod multicast;

pub use base::QuackCache;
pub use multicast::QuackCacheMulticast;

use std::fmt;
use std::error::Error;

use sidekick_utils::identifier::Identifier;

/// The packets in a quACKnowledgment that are currently in the cache.
///
/// Indexes refer to the index in the ordered cache view.
#[derive(Debug, PartialEq, Eq, Default, Clone)]
pub struct DecodeResult {
    /// One *plus* the index of the latest acknowledged packet.
    /// The value is 0 if no packets are acknowledged.
    pub last_index: usize,
    /// Indexes of packets before the latest acknowledged packet that were
    /// not acknowledged, in increasing order.
    pub missing_indexes: Vec<usize>,
}

/// Types of errors when decoding the quACK.
#[derive(Debug, PartialEq, Eq)]
pub enum DecodeError {
    /// The client should only send quACKs if it has observed at least 1 packet.
    EmptyClientQuack,
    /// The threshold of the received quACK does not match our own threshold.
    InvalidThreshold { expected: usize, actual: usize },
    /// Number of missing packets exceeds threshold.
    ExceededThreshold {
        num_missing: usize,
        threshold: usize,
    },
    /// The last value the client received is not an identifier of a known
    /// packet that is currently or was previously in our cache.
    MissingLastValue { identifier: Identifier },
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            DecodeError::EmptyClientQuack => {
                write!(f, "Empty client quack")
            }
            DecodeError::InvalidThreshold { expected, actual } => {
                write!(f, "Invalid threshold {} != {}", expected, actual)
            }
            DecodeError::ExceededThreshold {
                num_missing,
                threshold,
            } => write!(
                f,
                "Number of missing packets exceeds threshold {} > {}",
                num_missing, threshold
            ),
            DecodeError::MissingLastValue { identifier } => {
                write!(f, "Missing last value {}", identifier)
            }
        }
    }
}

impl Error for DecodeError {}
