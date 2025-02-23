use std::io;
use std::net::SocketAddr;
use std::sync::Arc;

use clap::{Parser, Subcommand};
use log::{trace, debug, info};
use tokio::sync::mpsc;
use tokio::net::UdpSocket;
use tokio::time::{Instant, Duration};

use media::{Packet, BufferedPackets, Statistics};
use media::{PAYLOAD_SIZE, TIMEOUT_SEQNO};


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

async fn listen_incoming(
    sock: Arc<UdpSocket>, nack_frequency: Duration,
) -> io::Result<()> {
    // Listen for incoming packets.
    loop {
        let mut stats = Statistics::new();
        let mut pkts = BufferedPackets::new();
        let mut payload = [0; PAYLOAD_SIZE];
        debug!("webrtc server is now listening");
        loop {
            let (len, addr) = sock.recv_from(&mut payload).await?;
            assert_eq!(len, PAYLOAD_SIZE);
            let packet = Packet::from_payload(&payload);
            trace!("received seqno {} ({} bytes)", packet.seqno, len);
            assert!(!packet.is_nack);
            if packet.seqno == TIMEOUT_SEQNO {
                debug!("timeout message received");
                break;
            }
            let now = Instant::now();
            pkts.recv_seqno(packet.seqno, now);
            while let Some(time_recv) = pkts.pop_seqno() {
                stats.add_value(now - time_recv);
            }
            for seqno in pkts.nacks_to_send(now, nack_frequency) {
                Packet::new_nack(seqno).fill_payload(&mut payload);
                sock.send_to(&payload, addr).await?;
            }
        }

        // Print statistics before exiting.
        stats.print_statistics();

        // Process remaining timeout messages.
        tokio::time::sleep(Duration::from_secs(1)).await;
        while sock.try_recv(&mut payload).is_ok() {}
    }
}

/// Listen to the mpsc channel and actually send packets on the UDP socket.
/// Receives sequence numbers and random identifiers and fills the packets.
async fn send_data(
    sock: Arc<UdpSocket>,
    mut rx: mpsc::Receiver<u32>,
) -> io::Result<()> {
    let mut payload = [0xFF; PAYLOAD_SIZE];
    tokio::spawn(async move {
        while let Some(seqno) = rx.recv().await {
            Packet::new_data(seqno).fill_payload(&mut payload);
            sock.send(&payload).await.unwrap();
        }
    });
    Ok(())
}

/// Spawn a thread that listens for end-to-end NACKs and retransmit packets
/// when requested.
fn listen_for_nacks(sock: Arc<UdpSocket>, tx: mpsc::Sender<u32>) {
    let mut payload = [0xFF; PAYLOAD_SIZE];
    tokio::spawn(async move {
        loop {
            let len = sock.recv(&mut payload).await.unwrap();
            assert_eq!(len, PAYLOAD_SIZE);
            let seqno = Packet::from_payload(&payload).seqno;
            debug!("retransmit {} from nack", seqno);
            tx.send(seqno).await.unwrap();
        }
    });
}

/// Send a stream of packets at the specified frequency with the given payload.
/// When the timeout is reached, send several timeout packets and return.
async fn stream_data(
    tx: mpsc::Sender<u32>,
    timeout: Duration,
    frequency: Duration,
) -> io::Result<()> {
    let mut interval = tokio::time::interval(frequency);
    let start = Instant::now();

    // Send packets with increasing sequence numbers until the elapsed time
    // is greater than the timeout.
    for seqno in 1..u32::MAX {
        interval.tick().await;
        trace!("send {}", seqno);
        tx.send(seqno).await.unwrap();
        if Instant::now() - start > timeout {
            break;
        }
    }

    // Send the timeout message. Do it a bunch and hope one makes it through.
    info!("sending timeout message");
    for _ in 0..100 {
        tx.send(TIMEOUT_SEQNO).await.unwrap();
    }
    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();
    let args = Cli::parse();
    let frequency = Duration::from_millis(args.frequency);
    let nack_frequency = Duration::from_millis(args.nack_frequency);

    // Start the server or client.
    match args.mode {
        Mode::Server => {
            let sock = {
                let addr = format!("0.0.0.0:{}", args.port);
                let sock = UdpSocket::bind(addr).await.unwrap();
                Arc::new(sock)
            };
            listen_incoming(sock, nack_frequency).await?;
        }
        Mode::Client { timeout, addr } => {
            let (tx, rx) = mpsc::channel(100);

            let sock = {
                let sock = UdpSocket::bind("0.0.0.0:0").await?;
                info!("sending from {:?}", sock.local_addr().unwrap());
                sock.connect(addr).await?;
                Arc::new(sock)
            };
            send_data(sock.clone(), rx).await?;
            listen_for_nacks(sock, tx.clone());
            stream_data(
                tx,
                Duration::from_secs(timeout),
                frequency,
            )
            .await?;
        }
    }
    Ok(())
}