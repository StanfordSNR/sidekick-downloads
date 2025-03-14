use std::ffi::{OsStr, CStr};
use std::os::{raw::c_char, unix::ffi::OsStrExt};
use std::path::Path;
use std::sync::Once;
use flexi_logger::{Logger, WriteMode, FileSpec};
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
pub extern "C" fn sidekick_init_logging(logfile: *const c_char) {
    INIT.call_once(|| {
        if logfile.is_null() {
            env_logger::init();
        } else {
            let logfile = unsafe { CStr::from_ptr(logfile) };
            let logfile = Path::new(OsStr::from_bytes(logfile.to_bytes()));
            Logger::try_with_env_or_str("error").unwrap()
                .log_to_file(FileSpec::try_from(logfile).unwrap())
                .write_mode(WriteMode::BufferAndFlush)
                .append()
                .start()
                .inspect_err(|e| eprintln!("Cannot start logger: {}", e))
                .unwrap();
        }
    });
}

#[no_mangle]
pub extern "C" fn sidekick_fixed_offset_to_id(
    bytes: *const u8, packet_length: usize, offset: usize,
) -> u32 {
    let slice = unsafe { std::slice::from_raw_parts(bytes, packet_length) };
    IdentifierFunc::FixedOffset(offset).to_id(slice)
}