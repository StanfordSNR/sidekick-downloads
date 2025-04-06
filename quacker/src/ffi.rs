use std::ffi::CStr;
use std::os::raw::c_char;
use std::net::{IpAddr, SocketAddr};

use libc::sockaddr_in;
use sidekick_utils::buffer::AddrKey;
use crate::{Quacker, UdpQuacker};

#[no_mangle]
pub extern "C" fn udp_quacker_new(
    threshold: usize, freq_pkts: u32, freq_ms: u64, addr: *const c_char, riblt: u8,
) -> *mut UdpQuacker {
    debug_assert!(!addr.is_null());
    let addr = unsafe { CStr::from_ptr(addr) };
    let addr = addr.to_str().unwrap().parse::<SocketAddr>().unwrap();
    let quacker = UdpQuacker::new(threshold, freq_pkts, freq_ms, addr, riblt != 0);
    Box::into_raw(Box::new(quacker))
}

#[no_mangle]
pub extern "C" fn udp_quacker_handle_sidekick_payload(
    quacker: *mut UdpQuacker, udp_payload: *const u8, len: usize,
) {
    debug_assert!(!quacker.is_null());
    debug_assert!(!udp_payload.is_null());
    let quacker = unsafe { &mut *quacker };
    let slice = unsafe { std::slice::from_raw_parts(udp_payload, len) };
    quacker.handle_sidekick_payload(slice);
}

#[no_mangle]
pub extern "C" fn udp_quacker_send_discovery(
    quacker: *mut UdpQuacker, base: *const AddrKey, n: usize,
) {
    debug_assert!(!quacker.is_null());
    debug_assert!(!base.is_null());
    let quacker = unsafe { &mut *quacker };
    let base = unsafe { *base };
    quacker.send_discovery(base, n);
}

#[no_mangle]
pub extern "C" fn udp_quacker_base_stoc_is_none(quacker: *const UdpQuacker) -> u8 {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &*quacker };
    quacker.base_stoc.is_none() as u8
}

#[no_mangle]
pub extern "C" fn udp_quacker_awaiting_disc_ack(quacker: *const UdpQuacker) -> u8 {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &*quacker };
    quacker.awaiting_disc_ack as u8
}

fn to_sockaddr_in(addr: SocketAddr) -> sockaddr_in {
    let s_addr = match addr.ip() {
        IpAddr::V4(ip) => ip.octets(),
        IpAddr::V6(_) => panic!("expected ipv4 address"),
    };
    sockaddr_in {
        sin_family: libc::AF_INET as u16,
        sin_port: addr.port().to_be(),
        sin_addr: libc::in_addr { s_addr: u32::from_be_bytes(s_addr) },
        sin_zero: [0; 8],
    }
}

#[no_mangle]
pub extern "C" fn udp_quacker_src_addr(quacker: *const UdpQuacker) -> sockaddr_in {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &*quacker };
    let result = to_sockaddr_in(quacker.src_addr());
    result
}

#[no_mangle]
pub extern "C" fn udp_quacker_dst_addr(quacker: *const UdpQuacker) -> sockaddr_in {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &*quacker };
    to_sockaddr_in(quacker.dst_addr())
}

#[no_mangle]
pub extern "C" fn udp_quacker_freq_pkts(quacker: *const UdpQuacker) -> u32 {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &*quacker };
    quacker.freq_pkts()
}

#[no_mangle]
pub extern "C" fn udp_quacker_freq_ms(quacker: *const UdpQuacker) -> u64 {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &*quacker };
    quacker.freq_ms()
}

#[no_mangle]
pub extern "C" fn udp_quacker_reset(quacker: *mut UdpQuacker) {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &mut *quacker };
    quacker.reset();
}

#[no_mangle]
pub extern "C" fn udp_quacker_insert(quacker: *mut UdpQuacker, time_ms: u64, id: u32) -> u8 {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &mut *quacker };
    quacker.insert(time_ms, id) as u8
}

#[no_mangle]
pub extern "C" fn udp_quacker_update_time(quacker: *mut UdpQuacker, time_ms: u64) -> u8 {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &mut *quacker };
    quacker.update_time(time_ms) as u8
}

#[no_mangle]
pub extern "C" fn udp_quacker_send_quack(quacker: *mut UdpQuacker, time_ms: u64) {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &mut *quacker };
    quacker.send_quack(time_ms);
}

#[no_mangle]
pub extern "C" fn udp_quacker_send_quack_with_hint(quacker: *mut UdpQuacker, time_ms: u64, num_symbols: usize) {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { &mut *quacker };
    quacker.send_quack_with_hint(time_ms, num_symbols);
}

#[no_mangle]
pub extern "C" fn udp_quacker_free(quacker: *mut UdpQuacker) {
    debug_assert!(!quacker.is_null());
    let quacker = unsafe { Box::from_raw(quacker) };
    drop(quacker);
}