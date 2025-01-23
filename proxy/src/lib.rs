pub mod socket;
pub mod stream;

pub const DEFAULT_MTU: usize = 1500;
pub const BUFFER_SIZE: usize = DEFAULT_MTU; // MTU