use std::io;
use std::net::{Ipv4Addr, SocketAddr};
use std::sync::Arc;

use clap::Parser;
use log::{debug, info};
use tokio::task;
use tokio::select;
use tokio::sync::Mutex;
use tokio::net::UdpSocket;
use tokio::time::{Instant, Duration};

use quacker::{current_time_ms, Quacker, UdpQuacker};
use sidekick_utils::buffer::AddrKey;
use sidekick_utils::packet::{DISCOVERY_FREQ_MS, NUM_DISCOVERY_PKTS};

use media::{Packet, BufferedPackets, Statistics};
use media::{PAYLOAD_SIZE, NACK_PAYLOAD_SIZE, TIMEOUT_SEQNO};
use media::sidekick::{parse_addr_key, QuackerConfig};


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
    /// Source server address.
    #[arg(long, default_value = "192.168.1.10:5201")]
    addr: SocketAddr,
    /// Multicast address to join.
    #[arg(long, default_value = "239.0.0.1")]
    multicast_ip: Ipv4Addr,
    /// Port to receive packets on.
    #[arg(long, default_value_t = 5202)]
    multicast_port: u16,
    /// Whether to enable the client quacker.
    #[arg(long, requires = "quacker_config")]
    quacker: bool,
    #[command(flatten)]
    quacker_config: Option<QuackerConfig>,
}

/// Listen for incoming packets on the UDP socket and handle.
async fn listen_incoming(
    sock: Sockets, quacker: Option<Arc<Mutex<UdpQuacker>>>, client_id: String,
    nack_frequency: Duration, nack_delay: Option<Duration>, timeout: Duration,
) -> io::Result<()> {
    let mut buf1 = [0u8; PAYLOAD_SIZE];
    let mut buf2 = [0u8; PAYLOAD_SIZE];
    let mut connection = None;
    let mut discovery_sent = current_time_ms();
    let start = Instant::now();
    loop {
        let (len, addr, is_multicast) = sock.recv_from(&mut buf1, &mut buf2).await;
        let mut buf = if is_multicast { buf2 } else { buf1 };
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

        let mut inserted = false;
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
                let addr_key = sock.multicast_addr_key();
                quacker.send_discovery_multicast(addr_key, NUM_DISCOVERY_PKTS);
                discovery_sent = current_time;
            }

            // Insert the received packet into the quACK.
            else
            {
                quacker.insert(current_time, data.identifier);
                inserted = true;
            }
        }

        // Add the data packet to the dejitter buffer and try to play data.
        assert_ne!(data.seqno, TIMEOUT_SEQNO);
        let now = Instant::now();
        if buffer.recv_seqno(data.seqno, now) {
            stats.add_spurious();
        }
        while let Some(time_recv) = buffer.pop_seqno() {
            stats.add_value(now - time_recv);
        }

        // Send NACKs for missing data.
        let nacks_to_send = buffer.nacks_to_send(now, nack_frequency, nack_delay);
        for &seqno in &nacks_to_send {
            let nack = Packet::new_nack(seqno);
            let len = nack.fill_payload(&mut buf);
            sock.send_to_server(&buf[..len]).await;
        }

        // Check for timeout.
        debug!(
            "receive data {}{}{}",
            data.seqno,
            if inserted { format!(" insert {}", data.identifier) } else { "".to_string() },
            if !nacks_to_send.is_empty() { format!(" nack {:?}", nacks_to_send) } else { "".to_string() },
        );
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
    sock: Sockets, init_frequency: Duration,
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
                let (len, _) = sock.recv_from_server(&mut payload).await;
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
        sock.send_to_server(&payload[..len]).await;
    }
    Ok(())
}

#[derive(Debug, Clone)]
struct Sockets {
    multicast_ip: Ipv4Addr,
    multicast_port: u16,
    unicast: Arc<UdpSocket>,
    multicast: Option<Arc<UdpSocket>>,
    server_addr: SocketAddr,
}

impl Sockets {
    async fn new(
        multicast_ip: Ipv4Addr, multicast_port: u16, server_addr: SocketAddr,
    ) -> io::Result<Self> {
        // Create the unicast port
        let sock_unicast = Arc::new(UdpSocket::bind("0.0.0.0:0").await?);
        info!("Ready to init unicast connection {:?}", sock_unicast.local_addr());

        Ok(Self {
            multicast_ip,
            multicast_port,
            unicast: sock_unicast,
            multicast: None,
            server_addr,
        })
    }

    async fn join_multicast(&mut self) -> io::Result<()> {
        // Create the multicast port after init ACK
        let local_ip = "0.0.0.0".parse().unwrap();
        let local_addr = (local_ip, self.multicast_port);
        let sock_multicast = Arc::new(UdpSocket::bind(local_addr).await?);
        sock_multicast.join_multicast_v4(self.multicast_ip, local_ip).unwrap();
        info!("Ready to receive multicast packets at {:?}", sock_multicast.local_addr());
        self.multicast = Some(sock_multicast);
        Ok(())
    }

    /// Returns the number of bytes received, the socket address of the packet
    /// sender, and whether the packet is from the multicast socket.
    async fn recv_from(&self, payload_unicast: &mut [u8], payload_multicast: &mut [u8]) -> (usize, SocketAddr, bool) {
        select! {
            Ok((len, addr)) = {
                self.unicast.recv_from(payload_unicast)
            } => (len, addr, false),
            Ok((len, addr)) = {
                self.multicast.as_ref().unwrap().recv_from(payload_multicast)
            } => (len, addr, true)
        }
    }

    async fn recv_from_server(&self, payload: &mut [u8]) -> (usize, SocketAddr) {
        self.unicast.recv_from(payload).await.unwrap()
    }

    async fn send_to_server(&self, payload: &[u8]) -> usize {
        self.unicast.send_to(payload, self.server_addr).await.unwrap()
    }

    fn multicast_addr_key(&self) -> AddrKey {
        let multicast_addr = SocketAddr::from(
            (self.multicast_ip, self.multicast_port));
        parse_addr_key(&self.server_addr, &multicast_addr).unwrap()
    }
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();
    let args = Cli::parse();
    let nack_frequency = Duration::from_millis(args.nack_frequency);
    let mut sock = Sockets::new(args.multicast_ip, args.multicast_port, args.addr).await?;

    // Initialize the client quacker if enabled.
    let quacker = if args.quacker {
        Some(args.quacker_config.unwrap().init_udp_quacker())
    } else {
        None
    };

    // Initialize the connection.
    {
        init_connection(sock.clone(), nack_frequency).await?;
        info!("Connected to the server");
        sock.join_multicast().await?;
    }

    // Start the client.
    {
        let timeout = Duration::from_secs(args.timeout);
        let nack_delay = if args.nack_delay > 0 {
            Some(Duration::from_millis(args.nack_delay))
        } else {
            None
        };
        listen_incoming(
            sock, quacker, args.client_id, nack_frequency, nack_delay, timeout,
        ).await?;
    }

    // Abort any sidekick tasks
    std::process::exit(0);
}
