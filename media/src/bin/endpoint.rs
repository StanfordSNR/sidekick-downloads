use std::io;
use std::net::{Ipv4Addr, SocketAddr};
use std::sync::Arc;

use clap::{Parser, Subcommand};
use log::{debug, info};
use tokio::task;
use tokio::sync::{mpsc, Mutex};
use tokio::sync::mpsc::error::SendError;
use tokio::net::UdpSocket;
use tokio::time::{Instant, Duration};

use quacker::{current_time_ms, Quacker, UdpQuacker};
use sidekick_utils::BUFFER_SIZE;
use sidekick_utils::buffer::AddrKey;
use sidekick_utils::discovery::{DISCOVERY_FREQ_MS, NUM_DISCOVERY_PKTS};

use media::{Packet, BufferedPackets, Statistics};
use media::{PAYLOAD_SIZE, NACK_PAYLOAD_SIZE, TIMEOUT_SEQNO};


const MPSC_CHANNEL_SIZE: usize = 100;
const NUM_TIMEOUT_MESSAGES: usize = 100;

#[derive(Debug, Parser)]
struct Cli {
    /// Port to receive packets on.
    #[arg(long, default_value_t = 5201)]
    port: u16,
    /// Frequency at which to send data packets, in ms.
    #[arg(long, default_value_t = 20)]
    frequency: u64,
    /// The NACK frequency, in ms. Typically the end-to-end RTT.
    #[arg(long)]
    nack_frequency: u64,
    /// The delay to wait after detecting loss before sending a NACK, in ms.
    #[arg(long, default_value_t = 0)]
    nack_delay: u64,
    /// The server listens for incoming connections while the client
    /// immediately sends data to the target address.
    #[command(subcommand)]
    mode: Mode,
    /// Whether to enable the client quacker.
    #[arg(long, requires = "quacker_config")]
    quacker: bool,
    #[command(flatten)]
    quacker_config: Option<QuackerConfig>,
}

#[derive(Debug, Parser, Clone)]
struct QuackerConfig {
    /// The threshold number of missing packets.
    #[arg(long, short = 't', default_value_t = 20)]
    threshold: usize,
    /// Frequency at which to quack, in ms.
    #[arg(long = "frequency-ms", default_value_t = 0)]
    frequency_ms: u64,
    /// Frequency at which to quack, in packets.
    #[arg(long = "frequency-pkts", default_value_t = 0)]
    frequency_pkts: u32,
    /// Address of the UDP socket to quack to e.g., <IP:PORT>. If missing,
    /// goes to stdout.
    #[arg(long = "target-addr", default_value = "172.16.2.10:5252")]
    target_addr: SocketAddr,
}

#[derive(Debug, Subcommand, PartialEq, Eq)]
enum Mode {
    /// Listen for incoming connections.
    Server,
    /// Immediately send data to the target address.
    Client {
        /// Number of seconds to stream data before sending a timeout message.
        #[arg(long, default_value_t = 60)]
        timeout: u64,
        /// Address of the other endpoint to send data to.
        #[arg(long, default_value = "172.16.2.10:5201")]
        addr: SocketAddr,
    },
}

impl Mode {
    fn is_client(&self) -> bool {
        match self {
            Mode::Server => { false }
            Mode::Client { timeout: _, addr: _ } => { true }
        }
    }
}

/// Parse `base_stoc` for the sidekick connection.
fn parse_addr_key(src: &SocketAddr, dst: &SocketAddr) -> Option<AddrKey> {
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
async fn listen_incoming_sidekick(quacker: Arc<Mutex<UdpQuacker>>) -> io::Result<()> {
    let sock = quacker.lock().await.src_sock();
    let mut buf = [0u8; BUFFER_SIZE];
    loop {
        // NOTE: This is a blocking UDP socket!
        let _len = sock.recv(&mut buf);
        quacker.lock().await.handle_sidekick_payload(&buf);
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

/// Listen for incoming packets on the UDP socket and handle.
async fn listen_incoming(
    should_loop: bool, quacker: Option<Arc<Mutex<UdpQuacker>>>,
    tx: mpsc::Sender<(Packet, SocketAddr)>, sock: Arc<UdpSocket>,
    frequency: Duration, nack_frequency: Duration, nack_delay: Option<Duration>,
) -> io::Result<()> {
    let mut buf = [0u8; PAYLOAD_SIZE];
    let mut connection = None;
    let mut discovery_sent = current_time_ms();
    loop {
        // Parse the incoming packet.
        let (len, addr) = sock.recv_from(&mut buf).await?;
        assert!(len == PAYLOAD_SIZE || len == NACK_PAYLOAD_SIZE);
        let data = Packet::from_payload(&buf);

        // Waiting for a data packet from a new connection. If it's a NACK
        // or timeout packet, assume it's from a previous connection. If it's
        // the server, also send data back in that direction.
        if connection.is_none() {
            if data.is_nack || data.seqno == TIMEOUT_SEQNO {
                continue;
            }
            let stats = Statistics::new();
            let buffer = BufferedPackets::new();
            let send_task = if should_loop {
                let tx = tx.clone();
                let send_task = task::spawn(async move {
                    gen_data_packets(tx, None, frequency, addr).await.unwrap();
                });
                Some(send_task)
            } else {
                None
            };
            connection = Some((addr, stats, buffer, send_task));
        }

        if let Some(ref quacker) = quacker {
            let mut quacker = quacker.lock().await;
            let current_time = current_time_ms();

            // Send <NUM_DISCOVERY_PKTS> packets if
            // (1) The quacker is enabled.
            // (2a) We haven't sent them already OR
            // (2b) More than <DISCOVERY_FREQ_MS> have elapsed since we
            //      last sent them, and we're awaiting a disc ACK.
            // (3) The base connection has bound to a local addr.
            if quacker.base_stoc.is_none() ||
               (quacker.awaiting_disc_ack && current_time >= discovery_sent + DISCOVERY_FREQ_MS * 1000)
            {
                if let Some(addr_key) = parse_addr_key(&addr, &sock.local_addr().unwrap()) {
                    quacker.send_discovery(addr_key, NUM_DISCOVERY_PKTS);
                    discovery_sent = current_time;
                }
            }

            // Insert the received packet into the quACK.
            else
            {
                info!("insert {}", data.identifier);
                quacker.insert(current_time, data.identifier);
            }
        }

        // Assume we handle one connection at a time.
        let (from_addr, ref mut stats, ref mut buffer, send_task) = connection.as_mut().unwrap();
        assert_eq!(*from_addr, addr);

        // Retransmit data if it's a NACK.
        if data.is_nack {
            debug!("retransmit data {}", data.seqno);
            let retx = Packet::new_data(data.seqno);
            tx.send((retx, addr.clone())).await.unwrap();
            continue;
        }

        // Otherwise it's a data packet. Timeout packets end the connection.
        if data.seqno == TIMEOUT_SEQNO {
            stats.print_statistics(None);
            if should_loop {
                send_task.as_mut().unwrap().abort();
                gen_timeout_packets(tx.clone(), from_addr.clone()).await.unwrap();
                connection = None;
                continue;
            } else {
                break;
            }
        }

        // Add the data packet to the dejitter buffer and try to play data.
        let now = Instant::now();
        if buffer.recv_seqno(data.seqno, now) {
            stats.add_spurious();
        }
        debug!("receive data {}", data.seqno);
        while let Some(time_recv) = buffer.pop_seqno() {
            stats.add_value(now - time_recv);
        }

        // Send NACKs for missing data.
        for seqno in buffer.nacks_to_send(now, nack_frequency, nack_delay) {
            debug!("nack {}", seqno);
            let nack = Packet::new_nack(seqno);
            tx.send((nack, addr.clone())).await.unwrap();
        }
    }
    Ok(())
}

/// Send outgoing packets on the UDP socket based on the mpsc channel.
async fn send_outgoing(
    mut rx: mpsc::Receiver<(Packet, SocketAddr)>, sock: Arc<UdpSocket>,
    bound: bool,
) -> io::Result<()> {
    let mut payload = [0xFF; PAYLOAD_SIZE];
    while let Some((packet, to)) = rx.recv().await {
        let len = packet.fill_payload(&mut payload);
        if bound {
            sock.send(&payload[..len]).await.unwrap();
        } else {
            sock.send_to(&payload[..len], to).await.unwrap();
        }
    }
    Ok(())
}

/// Generate a stream of media packets at the specified frequency. When the
/// timeout is reached, send several timeout packets and return.
async fn gen_data_packets(
    tx: mpsc::Sender<(Packet, SocketAddr)>,
    timeout: Option<Duration>, frequency: Duration, to: SocketAddr,
) -> Result<(), SendError<(Packet, SocketAddr)>> {
    let mut interval = tokio::time::interval(frequency);
    let start = Instant::now();
    for seqno in 1..u32::MAX {
        interval.tick().await;
        debug!("send data {}", seqno);
        let data = Packet::new_data(seqno);
        tx.send((data, to.clone())).await?;
        if let Some(timeout) = timeout {
            if Instant::now() > start + timeout {
                break;
            }
        }
    }

    gen_timeout_packets(tx, to).await?;
    Ok(())
}

/// Send the timeout message. Do it a bunch and hope one makes it through.
async fn gen_timeout_packets(
    tx: mpsc::Sender<(Packet, SocketAddr)>, to: SocketAddr,
) -> Result<(), SendError<(Packet, SocketAddr)>> {
    for _ in 0..NUM_TIMEOUT_MESSAGES {
        let data = Packet::new_data(TIMEOUT_SEQNO);
        tx.send((data, to.clone())).await?;
    }
    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();
    let args = Cli::parse();
    let frequency = Duration::from_millis(args.frequency);
    let nack_frequency = Duration::from_millis(args.nack_frequency);
    let nack_delay = if args.nack_delay > 0 {
        Some(Duration::from_millis(args.nack_delay))
    } else {
        None
    };

    // Bind to the local socket to listen to and send packets from.
    let sock = Arc::new(UdpSocket::bind(format!("0.0.0.0:{}", args.port)).await?);
    info!("Ready to accept incoming packets {:?}", sock.local_addr());

    // Channel for sending data on the UDP socket from one thread.
    let (tx, rx) = mpsc::channel(MPSC_CHANNEL_SIZE);
    let send_task = {
        let sock = sock.clone();
        let bound = args.mode.is_client();
        task::spawn(async move { send_outgoing(rx, sock, bound).await.unwrap() })
    };

    // Initialize the client quacker if enabled.
    let quacker = if args.quacker {
        let config = args.quacker_config.unwrap();
        let quacker = Arc::new(Mutex::new(UdpQuacker::new(
            config.threshold,
            config.frequency_pkts,
            config.frequency_ms,
            config.target_addr,
        )));

        // Ensure quACKs are sent at a time interval if specified.
        if config.frequency_ms > 0 {
            let quacker = quacker.clone();
            let quack_frequency = Duration::from_millis(config.frequency_ms);
            tokio::task::spawn(async move {
                send_quacks(quacker, quack_frequency).await;
            });
        }

        // Monitor packets on the sidekick connection.
        {
            let quacker = quacker.clone();
            task::spawn(async move {
                listen_incoming_sidekick(quacker.clone()).await.unwrap()
            });
        }
        Some(quacker)
    } else {
        None
    };

    // Start the server or client.
    match args.mode {
        Mode::Server => {
            listen_incoming(
                true, quacker, tx, sock, frequency, nack_frequency, nack_delay,
            ).await.unwrap();
        }
        Mode::Client { timeout, addr } => {
            sock.connect(addr).await?;
            let recv_task = {
                let tx = tx.clone();
                let sock = sock.clone();
                task::spawn(async move {
                    listen_incoming(
                        false, quacker, tx, sock, frequency, nack_frequency,
                        nack_delay,
                    ).await.unwrap()
                })
            };
            let data_task = {
                task::spawn(async move {
                    let timeout = Duration::from_secs(timeout);
                    gen_data_packets(tx, Some(timeout), frequency, addr).await.unwrap();
                })
            };

            // Wait for tasks to complete.
            data_task.await?;
            recv_task.await?;
            send_task.await?;
        }
    }

    // Abort any sidekick tasks
    std::process::exit(0);
}
