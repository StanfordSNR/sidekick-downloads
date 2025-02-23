use std::io;
use std::net::SocketAddr;
use std::sync::Arc;

use clap::{Parser, Subcommand};
use log::{debug, info};
use tokio::task;
use tokio::sync::mpsc::{self, error::SendError};
use tokio::net::UdpSocket;
use tokio::time::{Instant, Duration};

use media::{Packet, BufferedPackets, Statistics};
use media::{PAYLOAD_SIZE, TIMEOUT_SEQNO};


const MPSC_CHANNEL_SIZE: usize = 100;
const NUM_TIMEOUT_MESSAGES: usize = 100;

#[derive(Parser)]
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
    /// The server listens for incoming connections while the client
    /// immediately sends data to the target address.
    #[command(subcommand)]
    mode: Mode,
}

#[derive(Subcommand)]
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

/// Listen for incoming packets on the UDP socket and handle.
async fn listen_incoming(
    tx: mpsc::Sender<(Packet, SocketAddr)>, sock: Arc<UdpSocket>,
    frequency: Duration, nack_frequency: Duration, should_loop: bool,
) -> io::Result<()> {
    let mut buf = [0u8; PAYLOAD_SIZE];
    let mut connection = None;
    loop {
        // Parse the incoming packet.
        let (len, addr) = sock.recv_from(&mut buf).await?;
        assert_eq!(len, PAYLOAD_SIZE);
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
            stats.print_statistics();
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
        buffer.recv_seqno(data.seqno, now);
        debug!("receive data {}", data.seqno);
        while let Some(time_recv) = buffer.pop_seqno() {
            stats.add_value(now - time_recv);
        }

        // Send NACKs for missing data.
        for seqno in buffer.nacks_to_send(now, nack_frequency) {
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
) -> io::Result<()> {
    let mut payload = [0xFF; PAYLOAD_SIZE];
    while let Some((packet, to)) = rx.recv().await {
        packet.fill_payload(&mut payload);
        sock.send_to(&payload, to).await.unwrap();
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

    // Bind to the local socket to listen to and send packets from.
    let sock = Arc::new(UdpSocket::bind(format!("0.0.0.0:{}", args.port)).await?);
    info!("Ready to accept incoming packets {:?}", sock.local_addr());

    // Channel for sending data on the UDP socket from one thread.
    let (tx, rx) = mpsc::channel(MPSC_CHANNEL_SIZE);
    let send_task = {
        let sock = sock.clone();
        task::spawn(async move { send_outgoing(rx, sock).await.unwrap() })
    };

    // Start the server or client.
    match args.mode {
        Mode::Server => {
            listen_incoming(tx, sock, frequency, nack_frequency, true).await.unwrap();
        }
        Mode::Client { timeout, addr } => {
            let recv_task = {
                let tx = tx.clone();
                let sock = sock.clone();
                task::spawn(async move {
                    listen_incoming(tx, sock, frequency, nack_frequency, false).await.unwrap()
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
    Ok(())
}
