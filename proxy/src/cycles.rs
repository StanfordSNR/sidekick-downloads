const NUM_MEASUREMENTS: usize = 14;
const PRINT_NUM_PACKETS: u64 = 1000;
const HEADERS: [&str; NUM_MEASUREMENTS] = [
    "handle_packet", "basectos", "basestoc", "sidekick", "none", "encode",
    "deserialize", "decode", "cache_add", "retransmit", "cache_evict",
    "evict_missing", "evict_received", "drain",

];
const PRINT_INDEXES: [usize; 9] = [3, 6, 7, 8, 9, 10, 11, 12, 13];

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
        .map(|count| format!("{:.2}", count))
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
    println!("{} (total={},count={})", cycles_norm, total, count_prop);
}

unsafe fn rdtsc() -> u64 {
    core::arch::x86_64::_rdtsc()
}

pub fn cycles_start(idx: usize) {
    unsafe { START[idx] = rdtsc() };
}

pub fn cycles_stop(idx: usize) {
    unsafe {
        NUM_PACKETS[idx] += 1;
        CYCLES[idx] += rdtsc() - START[idx];
        if idx == 0 && NUM_PACKETS[0] % PRINT_NUM_PACKETS == 0 {
            print_cycles_summary();
        }
    }
}
