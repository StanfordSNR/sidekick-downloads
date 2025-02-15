use std::net::{SocketAddr, UdpSocket};
use std::sync::Arc;
use bincode;
use quack::PowerSumQuackU32;
use crate::{Quacker, BaseQuacker};

#[derive(Clone)]
pub struct UdpQuacker {
    quacker: BaseQuacker,
    src_sock: Arc<UdpSocket>,
    dst_addr: SocketAddr,
}

impl UdpQuacker {
    pub fn new(
        threshold: usize, freq_pkts: u32, freq_ms: u64, addr: SocketAddr,
    ) -> Self {
        Self {
            quacker: BaseQuacker::new(threshold, freq_pkts, freq_ms),
            src_sock: Arc::new(UdpSocket::bind("0.0.0.0:0").unwrap()),
            dst_addr: addr,
        }
    }

    pub fn src_sock(&self) -> Arc<UdpSocket> {
        self.src_sock.clone()
    }

    /// The socket address on which we expect to receive resets.
    ///
    /// The application is responsible for identifying reset packets in order
    /// to serialize them with base connection packets.
    pub fn src_addr(&self) -> SocketAddr {
        self.src_sock.local_addr().unwrap()
    }
}

impl Quacker for UdpQuacker {
    fn freq_pkts(&self) -> u32 {
        self.quacker.freq_pkts()
    }

    fn freq_ms(&self) -> u64 {
        self.quacker.freq_ms()
    }

    fn get_quack(&self) -> &PowerSumQuackU32 {
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
        let bytes = bincode::serialize(&self.get_quack()).unwrap();
        self.src_sock.send_to(&bytes, self.dst_addr).unwrap();
    }
}