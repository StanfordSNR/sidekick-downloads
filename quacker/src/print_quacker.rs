use quack::{Quack, QuackWrapper};
use crate::{Quacker, BaseQuacker};

#[derive(Clone)]
pub struct PrintQuacker {
    quacker: BaseQuacker,
}

impl PrintQuacker {
    pub fn new(
        riblt: bool, threshold: usize, freq_pkts: u32, freq_ms: u64,
    ) -> Self {
        Self {
            quacker: BaseQuacker::new(riblt, threshold, freq_pkts, freq_ms),
        }
    }
}

impl Quacker for PrintQuacker {
    fn freq_pkts(&self) -> u32 {
        self.quacker.freq_pkts()
    }

    fn freq_ms(&self) -> u64 {
        self.quacker.freq_ms()
    }

    fn get_quack(&self) -> &QuackWrapper {
        self.quacker.get_quack()
    }

    fn reset(&mut self) {
        self.quacker.reset();
    }

    fn insert(&mut self, time_ms: u64, id: u32) -> bool {
        let should_quack = self.quacker.insert(time_ms, id);
        if should_quack {
            self.send_quack(time_ms);
        }
        should_quack
    }

    fn update_time(&mut self, time_ms: u64) -> bool {
        let should_quack = self.quacker.update_time(time_ms);
        if should_quack {
            self.send_quack(time_ms);
        }
        should_quack
    }

    fn send_quack(&mut self, time_ms: u64) {
        self.quacker.send_quack(time_ms);
        println!("quack {}", self.get_quack().count());
    }
}