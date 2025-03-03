use std::sync::Once;
use crate::identifier::IdentifierFunc;

#[no_mangle]
pub static ID_OFFSET: usize = crate::ID_OFFSET;

#[no_mangle]
pub static UDP_PAYLOAD_OFFSET: usize = crate::UDP_PAYLOAD_OFFSET;

#[no_mangle]
pub static RESET_FREQ_MS: u64 = crate::packet::RESET_FREQ_MS;

#[no_mangle]
pub static DISCOVERY_FREQ_MS: u64 = crate::packet::DISCOVERY_FREQ_MS;

#[no_mangle]
pub static NUM_DISCOVERY_PKTS: usize = crate::packet::NUM_DISCOVERY_PKTS;

static INIT: Once = Once::new();

#[no_mangle]
pub extern "C" fn sidekick_init_logging() {
    INIT.call_once(|| {
        env_logger::init();
    });
}

#[no_mangle]
pub extern "C" fn sidekick_fixed_offset_to_id(
    bytes: *const u8, packet_length: usize, offset: usize,
) -> u32 {
    let slice = unsafe { std::slice::from_raw_parts(bytes, packet_length) };
    IdentifierFunc::FixedOffset(offset).to_id(slice)
}