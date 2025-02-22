//! Send dummy WebRTC messages to a UDP socket.
//!
//! The first four bytes of the payload indicate a packet sequence number.
//! The sequence numbers start at 1.
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
use rand::Rng;
use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tokio::time::{Duration, Instant};

#[derive(Parser)]
struct Cli {
    /// Server address to send dummy WebRTC messages to.
    #[arg(long)]
    server_addr: SocketAddr,
    /// Number of seconds to stream data before sending a timeout message.
    #[arg(long, short, default_value_t = 60)]
    timeout: u64,
    /// Number of bytes to send in the payload, including the sequence number.
    #[arg(long, short, default_value_t = 240)]
    bytes: usize,
    /// Frequency at which to send packets, in milliseconds.
    #[arg(long, short, default_value_t = 20)]
    frequency: u64,
}

/// NACKs just have 4 bytes for the sequence number.
const NACK_BUFFER_SIZE: usize = 4;

/// The sidekick sniffs at a certain offset in QUIC packets such that those
/// bytes are randomly-encrypted. I don't want to edit the sidekick code
/// currently so I will set the sequence numbers here in the same offset.
/// The sidekick offset also includes the Ethernet/IP/UDP headers since it
/// sniffs from a raw socket.
/// The randomly-encrypted payload in a QUIC packet with a short header is at
/// offset 63, including the Ethernet (14), IP (20), UDP (8) headers.
const ID_OFFSET: usize = 63 - (14 + 20 + 8);

/// A packet is considered missing if a packet with a sequence number greater
/// than this threshold away has been received. So packet 4 is considered
/// missing if packet 7 or greater has been received. If the last received
/// value is 7, at most packets 5 and 6 can be considered indeterminate.
const _REORDER_THRESHOLD: u32 = 3;

#[derive(Clone)]
struct PacketSender {
    channel: mpsc::Sender<(u32, u32)>,
}

impl PacketSender {
    async fn new(channel: mpsc::Sender<(u32, u32)>) -> io::Result<Self> {
        Ok(Self {
            channel,
        })
    }

    /// Send a packet with this sequence number to the server.
    async fn send(&mut self, seqno: u32) -> io::Result<()> {
        let id: u32 = rand::thread_rng().gen();

        // Add the new packet to the buffer and send the packet.
        // (may be some harmless reordering here)
        self.channel.send((seqno, id)).await.unwrap();
        Ok(())
    }
}

/// Listen to the mpsc channel and actually send packets on the UDP socket.
/// Receives sequence numbers and random identifiers and fills the packets.
async fn send_data(
    sock: Arc<UdpSocket>,
    bytes: usize,
    mut rx: mpsc::Receiver<(u32, u32)>,
) -> io::Result<()> {
    let mut payload = vec![0xFF; bytes];
    tokio::spawn(async move {
        while let Some((seqno, id)) = rx.recv().await {
            // Set the sequence number in the first 4 bytes.
            let seqno_bytes = seqno.to_be_bytes();
            payload[0] = seqno_bytes[0];
            payload[1] = seqno_bytes[1];
            payload[2] = seqno_bytes[2];
            payload[3] = seqno_bytes[3];

            // Set the random packet identifier at the QUIC offset.
            let id_bytes = id.to_be_bytes();
            payload[ID_OFFSET] = id_bytes[0];
            payload[ID_OFFSET + 1] = id_bytes[1];
            payload[ID_OFFSET + 2] = id_bytes[2];
            payload[ID_OFFSET + 3] = id_bytes[3];

            sock.send(&payload).await.unwrap();
        }
    });
    Ok(())
}

/// Spawn a thread that listens for end-to-end NACKs and retransmit packets
/// when requested.
fn listen_for_nacks(sock: Arc<UdpSocket>, mut sender: PacketSender) {
    let mut buf: [u8; NACK_BUFFER_SIZE] = [0; NACK_BUFFER_SIZE];
    tokio::spawn(async move {
        loop {
            let len = sock.recv(&mut buf).await.unwrap();
            assert_eq!(len, NACK_BUFFER_SIZE);
            let seqno = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]);
            debug!("retransmit {} from nack", seqno);
            sender.send(seqno).await.unwrap();
        }
    });
}

/// Send a stream of packets at the specified frequency with the given payload.
/// When the timeout is reached, send several timeout packets and return.
async fn stream_data(
    mut sender: PacketSender,
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
        sender.send(seqno).await?;
        if Instant::now() - start > timeout {
            break;
        }
    }

    // Send the timeout message. Do it a bunch and hope one makes it through.
    info!("sending timeout message");
    for _ in 0..100 {
        sender.send(u32::MAX).await?;
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
    let sender = PacketSender::new(tx).await?;
    send_data(sock.clone(), args.bytes, rx).await?;
    listen_for_nacks(sock, sender.clone());
    stream_data(
        sender,
        Duration::from_secs(args.timeout),
        Duration::from_millis(args.frequency),
    )
    .await?;
    Ok(())
}
