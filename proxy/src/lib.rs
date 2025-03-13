pub mod cache;
pub mod stream;

#[cfg(feature = "cycles")]
pub(crate) mod cycles;
#[cfg(not(feature = "cycles"))]
pub(crate) mod cycles {
	pub fn cycles_start(_idx: usize) {}
	pub fn cycles_stop(_idx: usize) {}
}

mod sidekick;
pub use sidekick::{Sidekick, SidekickMulticast};
