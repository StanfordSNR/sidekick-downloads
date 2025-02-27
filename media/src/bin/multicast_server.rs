use std::io;
use std::net::SocketAddr;
use std::collections::HashSet;
use std::sync::Arc;

use clap::Parser;
use log::{debug, info};
use tokio::task;
use tokio::sync::mpsc;
use tokio::sync::mpsc::error::SendError;
use tokio::net::UdpSocket;
use tokio::time::Duration;

use media::Packet;
use media::{PAYLOAD_SIZE, NACK_PAYLOAD_SIZE};


const MPSC_CHANNEL_SIZE: usize = 100;

#[derive(Debug, Parser)]
struct Cli {
    /// Port to receive packets on.
    #[arg(long, default_value_t = 5201)]
    port: u16,
    /// Frequency at which to send data packets, in ms.
    #[arg(long, default_value_t = 20)]
    frequency: u64,
}

/// Listen for incoming packets on the UDP socket and handle.
async fn listen_incoming(
    tx: mpsc::Sender<(Packet, SocketAddr)>, sock: Arc<UdpSocket>,
    frequency: Duration,
) -> io::Result<()> {
    let mut buf = [0u8; PAYLOAD_SIZE];
    let mut connections = HashSet::new();
    loop {
        // Parse the incoming packet.
        let (len, addr) = sock.recv_from(&mut buf).await?;
        let data = Packet::from_payload(&buf);
        assert!(len == NACK_PAYLOAD_SIZE);
        assert!(!data.is_init_ack);
        assert!(data.is_init || data.is_nack);

        // Handle non-data packets.
        if data.is_init {
            info!("Send init ACK {:?}", addr);
            tx.send((Packet::new_init_ack(), addr)).await.unwrap();
            if !connections.contains(&addr) {
                connections.insert(addr);
                let tx = tx.clone();
                task::spawn(async move {
                    gen_data_packets(tx, frequency, addr).await.unwrap();
                });
            }
            continue;
        }

        // Retransmit data if it's a NACK.
        if data.is_nack {
            debug!("retransmit data {}", data.seqno);
            let retx = Packet::new_data(data.seqno);
            tx.send((retx, addr.clone())).await.unwrap();
            continue;
        }
    }
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
    frequency: Duration, to: SocketAddr,
) -> Result<(), SendError<(Packet, SocketAddr)>> {
    let mut interval = tokio::time::interval(frequency);
    for seqno in 1..u32::MAX {
        interval.tick().await;
        debug!("send data {} -> {:?}", seqno, to);
        let data = Packet::new_data(seqno);
        tx.send((data, to.clone())).await?;
    }

    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();
    let args = Cli::parse();
    let frequency = Duration::from_millis(args.frequency);

    // Bind to the local socket to listen to and send packets from.
    let sock = Arc::new(UdpSocket::bind(format!("0.0.0.0:{}", args.port)).await?);
    info!("Ready to accept incoming packets {:?}", sock.local_addr());

    // Channel for sending data on the UDP socket from one thread.
    let (tx, rx) = mpsc::channel(MPSC_CHANNEL_SIZE);
    {
        let sock = sock.clone();
        task::spawn(async move { send_outgoing(rx, sock, false).await.unwrap() });
    }

    // // Send data packets to the multicast proxy.
    // {
    //     let tx = tx.clone();
    //     task::spawn(async move {
    //         gen_data_packets(tx, frequency, args.addr).await.unwrap();
    //     });
    // }

    // Start the server.
    listen_incoming(tx, sock, frequency).await.unwrap();
    Ok(())
}
