//! Send dummy WebRTC messages to a UDP socket.
//!
//! Send a packet every <FREQUENCY> milliseconds, containing <BYTES> bytes of
//! dummy data. (Sending a 240-byte payload every 20ms represents a 96 kbps
//! stream.) When <TIMEOUT> time has elapsed, send a timeout packet where the
//! sequence number is the max u32 integer. On receiving a NACK, retransmit
//! the missing packet that was identified in the NACK.
use std::io;
use std::net::SocketAddr;
use std::sync::Arc;

use clap::Parser;
use log::{debug, info, trace};
use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tokio::time::{Duration, Instant};

use media::{TIMEOUT_SEQNO, PAYLOAD_SIZE};
use media::Packet;

#[derive(Parser)]
struct Cli {
    /// Server address to send dummy WebRTC messages to.
    #[arg(long)]
    server_addr: SocketAddr,
    /// Number of seconds to stream data before sending a timeout message.
    #[arg(long, short, default_value_t = 60)]
    timeout: u64,
    /// Frequency at which to send packets, in milliseconds.
    #[arg(long, short, default_value_t = 20)]
    frequency: u64,
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

#[tokio::main(flavor = "current_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();

    let args = Cli::parse();
    let (tx, rx) = mpsc::channel(100);

    let sock = {
        let sock = UdpSocket::bind("0.0.0.0:0").await?;
        info!("sending from {:?}", sock.local_addr().unwrap());
        sock.connect(args.server_addr).await?;
        Arc::new(sock)
    };
    send_data(sock.clone(), rx).await?;
    listen_for_nacks(sock, tx.clone());
    stream_data(
        tx,
        Duration::from_secs(args.timeout),
        Duration::from_millis(args.frequency),
    )
    .await?;
    Ok(())
}
