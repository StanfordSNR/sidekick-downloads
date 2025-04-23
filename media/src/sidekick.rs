use std::io;
use std::net::{Ipv4Addr, SocketAddr};
use std::sync::Arc;

use clap::Parser;
use tokio::sync::{mpsc, Mutex};
use tokio::time::Duration;

use quacker::{current_time_ms, Quacker, UdpQuacker};
use sidekick_utils::{BUFFER_SIZE, buffer::AddrKey, packet::CachePolicy};


#[derive(Debug, Parser, Clone)]
pub struct QuackerConfig {
    /// The threshold number of missing packets.
    #[arg(long, short = 't', default_value_t = 20)]
    pub threshold: usize,
    /// Frequency at which to quack, in ms.
    #[arg(long = "frequency-ms", default_value_t = 0)]
    pub frequency_ms: u64,
    /// Frequency at which to quack, in packets.
    #[arg(long = "frequency-pkts", default_value_t = 0)]
    pub frequency_pkts: u32,
    /// Address of the UDP socket to quack to e.g., <IP:PORT>. If missing,
    /// goes to stdout.
    #[arg(long = "target-addr", default_value = "172.16.2.10:5252")]
    pub target_addr: SocketAddr,
    /// Whether to use the RIBLT quACK.
    #[arg(long)]
    pub riblt: bool,
    /// Whether to send quACKs with a hint for the number of symbols.
    #[arg(long)]
    pub hint: bool,
}

impl QuackerConfig {
    pub fn init_udp_quacker(
        &self, tx: Option<mpsc::Sender<Vec<u8>>>,
    ) -> Arc<Mutex<UdpQuacker>> {
        let quacker = Arc::new(Mutex::new(UdpQuacker::new(
            self.threshold,
            self.frequency_pkts,
            self.frequency_ms,
            self.target_addr,
            self.riblt,
            CachePolicy::Optimistic,
            sidekick_utils::packet::RESET_FREQ_MS,
        )));

        // Ensure quACKs are sent at a time interval if specified.
        if self.frequency_ms > 0 {
            let quacker = quacker.clone();
            let quack_frequency = Duration::from_millis(self.frequency_ms);
            tokio::task::spawn(async move {
                send_quacks(quacker, quack_frequency).await;
            });
        }

        // Monitor packets on the sidekick connection.
        {
            let quacker = quacker.clone();
            tokio::task::spawn(async move {
                listen_incoming_sidekick(
                    quacker.clone(), tx,
                ).await.unwrap()
            });
        }
        quacker
    }
}

/// Parse `base_stoc` for the sidekick connection.
pub fn parse_addr_key(src: &SocketAddr, dst: &SocketAddr) -> Option<AddrKey> {
    match (src, dst) {
        (SocketAddr::V4(src), SocketAddr::V4(dst)) => {
            if *dst.ip() == Ipv4Addr::new(0, 0, 0, 0) {
                None
            } else {
                let mut key = [0u8; 12];
                key[..4].copy_from_slice(&src.ip().octets());
                key[4..6].copy_from_slice(&src.port().to_be_bytes());
                key[6..10].copy_from_slice(&dst.ip().octets());
                key[10..12].copy_from_slice(&dst.port().to_be_bytes());
                Some(key)
            }
        }
        _ => panic!("IPv6 not supported"),
    }
}

/// Listen for incoming packets on the sidekick connection and handle.
async fn listen_incoming_sidekick(
    quacker: Arc<Mutex<UdpQuacker>>, tx: Option<mpsc::Sender<Vec<u8>>>,
) -> io::Result<()> {
    let sock = quacker.lock().await.src_sock();
    let mut buf = [0u8; BUFFER_SIZE];
    loop {
        // NOTE: This is a blocking UDP socket!
        let len = sock.recv(&mut buf)?;
        let res = quacker.lock().await.handle_sidekick_payload(&buf[..len]);
        if tx.is_some() && res.is_some() {
            tx.as_ref().unwrap().send(res.unwrap()).await.unwrap();
        }
    }
}

/// Send quacks at a specified frequency if there aren't many incoming packets.
async fn send_quacks(quacker: Arc<Mutex<UdpQuacker>>, frequency: Duration) {
    let mut interval = tokio::time::interval(frequency);
    loop {
        interval.tick().await;
        // Not exactly the algorithm but close enough.
        {
            let mut q = quacker.lock().await;
            let time_ms = current_time_ms();
            q.update_time(time_ms);
        }
    }
}
