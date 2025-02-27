use std::io;
use std::net::SocketAddr;
use std::sync::Arc;

use clap::Parser;
use log::{debug, info};
use tokio::task;
use tokio::sync::Mutex;
use tokio::net::UdpSocket;
use tokio::time::{Instant, Duration};

use media::{Packet, BufferedPackets, Statistics};
use media::{PAYLOAD_SIZE, NACK_PAYLOAD_SIZE, TIMEOUT_SEQNO};


#[derive(Debug, Parser)]
struct Cli {
    /// The unique client ID.
    #[arg(long)]
    client_id: String,
    /// The NACK frequency, in ms. Typically the end-to-end RTT.
    #[arg(long)]
    nack_frequency: u64,
    /// The delay to wait after detecting loss before sending a NACK, in ms.
    #[arg(long, default_value_t = 0)]
    nack_delay: u64,
    /// Number of seconds to stream data before sending a timeout message.
    #[arg(long, default_value_t = 60)]
    timeout: u64,
    /// Address of the other endpoint to send data to.
    #[arg(long, default_value = "172.16.2.10:5201")]
    addr: SocketAddr,
}

/// Listen for incoming packets on the UDP socket and handle.
async fn listen_incoming(
    sock: Arc<UdpSocket>, nack_frequency: Duration, nack_delay: Option<Duration>,
    timeout: Duration, client_id: String,
) -> io::Result<()> {
    let mut buf = [0u8; PAYLOAD_SIZE];
    let mut connection = None;
    let start = Instant::now();
    loop {
        let (len, addr) = sock.recv_from(&mut buf).await?;
        let data = Packet::from_payload(&buf);

        // Handle non-data packets.
        assert!(len == PAYLOAD_SIZE || len == NACK_PAYLOAD_SIZE);
        if len == NACK_PAYLOAD_SIZE {
            assert!(!data.is_nack);
            assert!(!data.is_init);
            if data.is_init_ack {
                continue;
            }
        }

        // Initialize the connection with the first data packet.
        if connection.is_none() {
            let stats = Statistics::new();
            let buffer = BufferedPackets::new(data.seqno);
            connection = Some((addr, stats, buffer));
        }
        let (from_addr, ref mut stats, ref mut buffer) = connection.as_mut().unwrap();
        assert_eq!(*from_addr, addr);

        // Add the data packet to the dejitter buffer and try to play data.
        assert_ne!(data.seqno, TIMEOUT_SEQNO);
        let now = Instant::now();
        if buffer.recv_seqno(data.seqno, now) {
            stats.add_spurious();
        }
        debug!("receive data {} <- {:?}", data.seqno, addr);
        while let Some(time_recv) = buffer.pop_seqno() {
            stats.add_value(now - time_recv);
        }

        // Send NACKs for missing data.
        for seqno in buffer.nacks_to_send(now, nack_frequency, nack_delay) {
            debug!("nack {}", seqno);
            let nack = Packet::new_nack(seqno);
            let len = nack.fill_payload(&mut buf);
            sock.send(&buf[..len]).await.unwrap();
        }

        // Check for timeout.
        if now >= start + timeout {
            let prefix = format!("[ID{}] ", client_id);
            stats.print_statistics(Some(prefix));
            break;
        }
    }
    Ok(())
}

/// Send the initial message. Do it a bunch and hope one makes it through.
async fn init_connection(
    sock: Arc<UdpSocket>, init_frequency: Duration,
) -> io::Result<()> {
    let discovered = Arc::new(Mutex::new(false));
    let mut payload = [0xFF; PAYLOAD_SIZE];
    let mut interval = tokio::time::interval(init_frequency);

    {
        let sock = sock.clone();
        let discovered = discovered.clone();
        task::spawn(async move {
            let mut payload = [0xFF; PAYLOAD_SIZE];
            loop {
                let len = sock.recv(&mut payload).await.unwrap();
                if len != NACK_PAYLOAD_SIZE {
                    continue;
                }
                let packet = Packet::from_payload(&payload);
                if packet.is_init_ack {
                    debug!("Received init ACK");
                    *discovered.lock().await = true;
                    break;
                }
            }
        });
    }

    loop {
        interval.tick().await;
        if *discovered.lock().await {
            break;
        }
        let init = Packet::new_init();
        let len = init.fill_payload(&mut payload);
        debug!("Sending init");
        sock.send(&payload[..len]).await.unwrap();
    }
    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();
    let args = Cli::parse();
    let nack_frequency = Duration::from_millis(args.nack_frequency);

    // Bind to the local socket to listen to and send packets from.
    let sock = Arc::new(UdpSocket::bind("0.0.0.0:0").await?);
    sock.connect(args.addr).await?;
    info!("Ready to accept incoming packets {:?} -> {:?}", sock.local_addr(), sock.peer_addr());

    // Initialize the connection.
    {
        let sock = sock.clone();
        init_connection(sock, nack_frequency).await?;
        info!("Connected to the server");
    }

    // Start the client.
    {
        let sock = sock.clone();
        let timeout = Duration::from_secs(args.timeout);
        let nack_delay = if args.nack_delay > 0 {
            Some(Duration::from_millis(args.nack_delay))
        } else {
            None
        };
        listen_incoming(
            sock, nack_frequency, nack_delay, timeout, args.client_id,
        ).await?;
    }
    Ok(())
}
