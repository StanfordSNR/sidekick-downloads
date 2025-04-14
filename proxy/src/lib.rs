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
