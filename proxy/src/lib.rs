pub mod socket;
pub mod stream;

pub const DEFAULT_MTU: usize = 1500;
// Ethernet (14), padding in case of VLAN and CRC
// Round up in case of padding
pub const BUFFER_SIZE: usize = (DEFAULT_MTU + 14 + 8).next_power_of_two();