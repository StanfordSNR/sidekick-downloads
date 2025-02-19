use std::time::{SystemTime, UNIX_EPOCH};

mod quacker;
mod print_quacker;
mod udp_quacker;

pub use quacker::{Quacker, BaseQuacker};
pub use print_quacker::PrintQuacker;
pub use udp_quacker::UdpQuacker;

pub fn current_time_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64
}

mod ffi;