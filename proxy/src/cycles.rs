#[cfg(feature = "cycles_base")]
mod config {
    pub const PRINT_NUM_PACKETS: u64 = 1000;
    pub const NUM_MEASUREMENTS: usize = 9;
    pub const HEADERS: [&str; NUM_MEASUREMENTS] = [
        "connection_type", "forward", "handle_base_packet_from_server", // handle_packet
        "hash_table", "cache_add", "reset", // handle_base_packet_from_server
        "check_capacity", "parse_id", "push", // add

    ];
    pub const PRINT_INDEXES: [usize; 8] = [0, 1, 2, 3, 4, 6, 7, 8];
}

#[cfg(feature = "cycles_quack")]
mod config {
    pub const PRINT_NUM_PACKETS: u64 = 500;
    pub const NUM_MEASUREMENTS: usize = 18;
    pub const HEADERS: [&str; NUM_MEASUREMENTS] = [
        "connection_type", "handle_sidekick_packet_from_client", // handle_packet
        "parse_disc", "parse_quack", "handle_disc", "handle_quack", // handle_sidekick_packet_from_client
        "hash_table", "decode", "retransmit", "evict", "reset", // handle_quack_from_client
        "evict_drain", "evict_nbytes", "evict_missing", // evict
        "check_valid_quack", "insert", "subtract", "decode", // decode
    ];
    pub const PRINT_INDEXES: [usize; 18] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17];
}

use config::*;

static mut START: [u64; NUM_MEASUREMENTS] = [0; NUM_MEASUREMENTS];
static mut CYCLES: [u64; NUM_MEASUREMENTS] = [0; NUM_MEASUREMENTS];
static mut NUM_PACKETS: [u64; NUM_MEASUREMENTS] = [0; NUM_MEASUREMENTS];

unsafe fn print_cycles_summary() {
    let total = NUM_PACKETS[0];
    let cycles_norm = PRINT_INDEXES
        .iter()
        .map(|&i| if NUM_PACKETS[i] == 0 {
            0
        } else {
            CYCLES[i] / NUM_PACKETS[i]
        })
        .map(|cycles| cycles.to_string())
        .collect::<Vec<_>>()
        .join(",");
    let count_prop = PRINT_INDEXES
        .iter()
        .map(|&i| NUM_PACKETS[i])
        .map(|count| (count as f64) / (total as f64))
        .map(|count| format!("{:.3}", count))
        .collect::<Vec<_>>()
        .join(",");
    if total == PRINT_NUM_PACKETS {
        let headers = PRINT_INDEXES
            .iter()
            .map(|&i| HEADERS[i])
            .collect::<Vec<_>>()
            .join(",");
        println!("{}", headers);
    }
    println!("{} (total={},prop={})", cycles_norm, total, count_prop);
}

unsafe fn rdtsc() -> u64 {
    core::arch::x86_64::_rdtsc()
}

pub fn _cycles_start(idx: usize) {
    unsafe { START[idx] = rdtsc() };
}

pub fn _cycles_stop(idx: usize) {
    unsafe {
        NUM_PACKETS[idx] += 1;
        CYCLES[idx] += rdtsc() - START[idx];
        if idx == 0 && NUM_PACKETS[0] % PRINT_NUM_PACKETS == 0 {
            print_cycles_summary();
        }
    }
}

pub fn _cycles_dummy(_idx: usize) {}

#[cfg(all(feature = "cycles_base", not(feature = "cycles_quack")))]
pub use {
    _cycles_start as cycles_base_start,
    _cycles_stop as cycles_base_stop,
    _cycles_dummy as cycles_quack_start,
    _cycles_dummy as cycles_quack_stop,
};

#[cfg(all(feature = "cycles_quack", not(feature = "cycles_base")))]
pub use {
    _cycles_dummy as cycles_base_start,
    _cycles_dummy as cycles_base_stop,
    _cycles_start as cycles_quack_start,
    _cycles_stop as cycles_quack_stop,
};
