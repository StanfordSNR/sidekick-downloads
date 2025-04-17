pub mod cache;
pub mod stream;

#[cfg(any(feature = "cycles_base", feature = "cycles_quack"))]
pub(crate) mod cycles;
#[cfg(all(not(feature = "cycles_base"), not(feature = "cycles_quack")))]
pub(crate) mod cycles {
    pub fn cycles_base_start(_idx: usize) {}
    pub fn cycles_base_stop(_idx: usize) {}
    pub fn cycles_quack_start(_idx: usize) {}
    pub fn cycles_quack_stop(_idx: usize) {}
}

mod sidekick;
pub use sidekick::{Sidekick, SidekickMulticast};

#[cfg(any(feature = "cycles_base", feature = "cycles_quack"))]
pub fn pin_to_cpu(cpu_id: usize, isol_cpu: bool) {
    let result;
    // Try to isolate the CPU (temporarily)
    // Note that this won't be as effective as GRUB --
    // it only provides partial isolation and, if some processes
    // are not movable, the command will fail.
    if isol_cpu {
        let cpu = format!("--cpu={}", cpu_id);
        let status = std::process::Command::new("sudo")
            .args(["cset", "shield", &cpu, "--kthread=on", "--force"])
            .status()
            .expect("Failed to execute cset");
        if !status.success() {
            panic!("Failed to execute cset (cpu: {}): {}", cpu_id, status);
        }
    }
    log::info!("Used cset to isolate CPU {}", cpu_id);

    // Set affinity
    unsafe {
        let mut set: libc::cpu_set_t = std::mem::zeroed();
        libc::CPU_ZERO(&mut set);
        libc::CPU_SET(cpu_id, &mut set);
        result = libc::sched_setaffinity(0 /* curr process */,
                                         std::mem::size_of::<libc::cpu_set_t>(),
                                         &set);
    }
    assert!(result == 0,
            "Failed to set CPU affinity for current process");
    log::info!("Set CPU affinity for current process: {}", cpu_id);
}


#[cfg(all(not(feature = "cycles_base"), not(feature = "cycles_quack")))]
pub fn pin_to_cpu(_cpu_id: usize, _isol_cpu: bool) {}