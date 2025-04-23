use std::io;
use std::net::SocketAddr;
use std::sync::Arc;
use std::fs::File;
use std::path::Path;

use clap::{Parser, Subcommand};
use log::debug;
use flexi_logger::{Logger, WriteMode, FileSpec};
use tokio::task;
use tokio::sync::{mpsc, Mutex};
use tokio::sync::mpsc::error::SendError;
use tokio::net::UdpSocket;
use tokio::time::{Instant, Duration};

use quacker::{current_time_ms, Quacker, UdpQuacker};
use sidekick_utils::packet::{DISCOVERY_FREQ_MS, NUM_DISCOVERY_PKTS};

use media::{Packet, BufferedPackets, Statistics, AudioTimestamper};
use media::{PAYLOAD_SIZE, NACK_PAYLOAD_SIZE, TIMEOUT_SEQNO, INITIAL_SEQNO};
use media::sidekick::{parse_addr_key, QuackerConfig};


const MPSC_CHANNEL_SIZE: usize = 100;
const NUM_INIT_MESSAGES: usize = 10;
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
    /// Whether to send quACKs when sending a NACK.
    #[arg(long)]
    send_on_nack: bool,
    /// Logfile to write rust logs to (optional)
    /// Must be a complete, valid path including directory.
    /// This should be set for loglevel = TRACE. Excessively logging to
    /// stdout/stderr can interfere with Mininet's packet buffers.
    #[arg(long, short = 'f')]
    logfile: Option<String>,
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

/// Listen for incoming packets on the UDP socket and handle.
async fn listen_incoming(
    should_loop: bool, quacker: Option<(Arc<Mutex<UdpQuacker>>, QuackerConfig)>,
    tx: mpsc::Sender<(Packet, SocketAddr)>, sock: Arc<UdpSocket>,
    frequency: Duration, nack_frequency: Duration, nack_delay: Option<Duration>,
    send_on_nack: bool,
) -> io::Result<()> {
    let mut buf = [0u8; PAYLOAD_SIZE];
    let mut connection = None;
    let mut discovery_sent = current_time_ms();
    let mut timestamper: Option<AudioTimestamper> = None;
    const FIRST_SEQNO: u32 = 1;
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
            let buffer = BufferedPackets::new(FIRST_SEQNO);
            let quack_buffer = BufferedPackets::new(FIRST_SEQNO);
            let send_task = if should_loop {
                let tx = tx.clone();
                let send_task = task::spawn(async move {
                    gen_data_packets(tx, None, frequency, addr).await.unwrap();
                });
                Some(send_task)
            } else {
                None
            };
            connection = Some((addr, stats, buffer, quack_buffer, send_task));
        }

        let current_time = current_time_ms();
        let mut should_quack = false;
        if let Some((ref quacker, _)) = quacker {
            let mut quacker = quacker.lock().await;

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
                debug!("insert {}", data.identifier);
                should_quack = quacker.insert(current_time, data.identifier);
            }
        }

        // Assume we handle one connection at a time.
        let (
            from_addr,
            ref mut stats,
            ref mut buffer,
            ref mut quack_buffer,
            send_task,
        ) = connection.as_mut().unwrap();
        assert_eq!(*from_addr, addr);

        // Retransmit data if it's a NACK.
        let now = Instant::now();
        if data.is_nack
        {
            debug!("retransmit data {} {}", data.seqno, data.seqno + 1);
            let retx = Packet::new_data(data.seqno);
            tx.send((retx, addr.clone())).await.unwrap();
        }
        // Otherwise it's a data packet. Timeout packets end the connection.
        else if data.seqno == TIMEOUT_SEQNO
        {
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
        // Ignore the initial seqno
        else if data.seqno == INITIAL_SEQNO {}
        // Add the data packet to the dejitter buffer and try to play data.
        else {
            // Each seqno represents two frames of data that overlap with
            // adjacent seqnos by one frame.
            buffer.recv_seqno(data.seqno, now);
            buffer.recv_seqno(data.seqno + 1, now);
            // Use a separate buffer for identifying spurious *packets* and
            // when we would need to NACK a *packet* (and not frame).
            if quack_buffer.recv_seqno(data.seqno, now) {
                stats.add_spurious();
            }
            if timestamper.is_none() {
                let num_seqnos = data.seqno - FIRST_SEQNO;
                timestamper = Some(AudioTimestamper::new(
                    FIRST_SEQNO, now - num_seqnos * frequency, frequency,
                ));
            }
            debug!("receive data {} {}", data.seqno, data.seqno + 1);
            while let Some(res) = buffer.pop_seqno() {
                // // dejitter buffer delay
                // let stat = now - res.time_recv;
                // // playback delay with an infinite length jitter buffer
                // let stat = {
                //     let num_seqnos = res.seqno - FIRST_SEQNO;
                //     let time_prod = time_init.unwrap() + frequency * num_seqnos;
                //     now - time_prod
                // };
                // playback delay with no jitter buffer
                let stat = {
                    res.time_recv - timestamper.as_ref().unwrap().ts(res.seqno)
                };
                stats.add_value(stat);
            }
            while quack_buffer.pop_seqno().is_some() {}
        }

        // Send NACKs for missing data.
        let (nacks_to_send, _) = buffer.nacks_to_send(now, nack_frequency, nack_delay);
        for seqno in nacks_to_send {
            debug!("nack {}", seqno);
            let nack = Packet::new_nack(seqno);
            tx.send((nack, addr.clone())).await.unwrap();
            stats.add_nack();
        }

        // Explicitly send a quACK when missing data.
        let (quacks_to_send, _) = quack_buffer.nacks_to_send(now, nack_delay.unwrap_or(nack_frequency), None);
        let num_missing = quacks_to_send.len();
        if should_quack || (send_on_nack && num_missing > 0) {
            if let Some((ref quacker, ref config)) = quacker {
                let mut quacker = quacker.lock().await;
                if config.hint {
                    // Add a small buffer of 4 for missing NACKs
                    quacker.send_quack_with_hint(current_time, num_missing + 4);
                } else {
                    quacker.send_quack(current_time);
                }
            }
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
        debug!("send data {} {}", seqno, seqno + 1);
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

async fn gen_init_packets(
    tx: mpsc::Sender<(Packet, SocketAddr)>,
    timeout: Duration, to: SocketAddr,
) -> Result<(), SendError<(Packet, SocketAddr)>> {
    debug!("send init {}", INITIAL_SEQNO);
    for _ in 0..NUM_INIT_MESSAGES {
        let data = Packet::new_data(INITIAL_SEQNO);
        tx.send((data, to.clone())).await?;
    }
    tokio::time::sleep(timeout).await;
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
    let args = Cli::parse();
    if let Some(logfile) = args.logfile {
        if !Path::new(&logfile).exists() {
            eprintln!("Creating logfile {}", logfile);
            let _ = File::create(&logfile).unwrap();
        }
        Logger::try_with_env_or_str("error").unwrap()
            .log_to_file(FileSpec::try_from(&logfile).unwrap())
            .write_mode(WriteMode::BufferAndFlush)
            .append()
            .start()
            .inspect_err(|e| eprintln!("Cannot start logger: {}", e))
            .unwrap();
    } else {
        env_logger::init();
    }
    let frequency = Duration::from_millis(args.frequency);
    let nack_frequency = Duration::from_millis((1.1 * args.nack_frequency as f64) as u64);
    let nack_delay = if args.nack_delay > 0 {
        Some(Duration::from_millis(args.nack_delay))
    } else {
        None
    };

    // Bind to the local socket to listen to and send packets from.
    let sock = Arc::new(UdpSocket::bind(format!("0.0.0.0:{}", args.port)).await?);
    eprintln!("Ready to accept incoming packets {:?}", sock.local_addr());

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
        let quacker = config.init_udp_quacker(None);
        Some((quacker, config))
    } else {
        None
    };

    // Start the server or client.
    match args.mode {
        Mode::Server => {
            listen_incoming(
                true, quacker, tx, sock, frequency, nack_frequency, nack_delay,
                args.send_on_nack,
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
                        nack_delay, args.send_on_nack,
                    ).await.unwrap()
                })
            };
            let data_task = {
                task::spawn(async move {
                    let timeout = Duration::from_secs(timeout);
                    gen_init_packets(tx, timeout, addr).await.unwrap();
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
