mod sidekick;
mod quacker;
mod print_quacker;
mod udp_quacker;

pub use quacker::{Quacker, BaseQuacker};
pub use print_quacker::PrintQuacker;
pub use udp_quacker::UdpQuacker;

pub fn current_time_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64
}

use clap::Parser;
use log::{trace, debug, info, warn};
use sidekick::Sidekick;
use std::net::{SocketAddr, Ipv4Addr};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::net::UdpSocket;
use tokio::sync::oneshot;
use tokio::time::{self, Duration};

use sidekick_utils::{BUFFER_SIZE, ID_OFFSET};
use sidekick_utils::discovery::DiscoveryPayload;
use sidekick_utils::socket::{SockAddr, Socket};
use sidekick_utils::buffer::{UdpParser, Direction};
use sidekick_utils::identifier::IdentifierFunc;
use quack::PowerSumQuack;

/// Sends quACKs in the sidekick protocol, receives data in the base protocol.
#[derive(Parser)]
struct Cli {
    /// Interface to listen on e.g., `eth1'.
    #[arg(long, short = 'i')]
    interface: String,
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
    #[arg(long = "target-addr")]
    target_addr: SocketAddr,
}

async fn send_quacks(
    sc: Arc<Mutex<Sidekick>>,
    rx: oneshot::Receiver<()>,
    socket: UdpSocket,
    addr: SocketAddr,
    frequency_ms: u64,
) {
    assert!(frequency_ms > 0);
    rx.await
        .expect("couldn't receive notice that 1st packet was sniffed");
    let mut interval = time::interval(Duration::from_millis(frequency_ms));

    // For the first packet, send a discovery
    // Send 2 dups to account for random loss
    let mut base = sc.lock()
                     .unwrap()
                     .base_stoc
                     .expect("First packet received but no base connection");
    Sidekick::send_discovery(&socket, &base, addr, 3).await;

    // The first tick completes immediately
    interval.tick().await;
    loop {
        let quack;
        let disc;
        interval.tick().await;
        {
            let sc = sc.lock().unwrap();
            quack = sc.quack();
            base = sc.base_stoc.expect("No base connection");
            disc = sc.awaiting_disc_ack;
        }
        // Send discovery if waiting for ACK. Could indicate an
        // update to the base connection or a lost Discover/DiscoverAck.
        if disc {
            // Send 2 dups to account for random loss
            Sidekick::send_discovery(&socket, &base, addr, 3).await;
        }
        // Send quack
        let bytes = bincode::serialize(&quack).unwrap();
        info!("quack {}", quack.count());
        if socket.send_to(&bytes, addr).await.is_err() {
            break;
        }
    }
}

async fn start_sniffer(
    quacker: Arc<Mutex<UdpQuacker>>,
    interface: &str,
) -> Result<(), String> {
    let identifier_func = IdentifierFunc::FixedOffset(ID_OFFSET);
    let recvsock = Socket::new(interface.to_string())?;
    recvsock.set_promiscuous()?;

    // Note the quack_addr is assumed to never change
    let quack_addr = quacker.lock().unwrap().dst_addr();

    // Loop over received packets
    let mut buf: [u8; BUFFER_SIZE] = [0; BUFFER_SIZE];
    info!("tapping socket on fd={} interface={}", recvsock.fd, interface);
    let mut addr = SockAddr::new_sockaddr_ll();
    let ip_protocol = (libc::ETH_P_IP as u16).to_be();
    while let Ok(n) = recvsock.recvfrom(&mut addr, &mut buf) {
        trace!("received {} bytes: {:?}", n, buf);
        if Direction::Incoming != addr.sll_pkttype.into() {
            continue;
        }
        if addr.sll_protocol != ip_protocol {
            trace!("not IP packet: {}", addr.sll_protocol);
            continue;
        }
        if !UdpParser::is_udp(&buf) {
            trace!("not UDP packet");
            continue;
        }

        // If this is an incoming sidekick packet from the proxy, handle it.
        if Ipv4Addr::from(UdpParser::parse_src_ip(&buf)) == quack_addr.ip() &&
           u16::from_be_bytes(UdpParser::parse_src_port(&buf)) == quack_addr.port() {
            if let Some(disc) = DiscoveryPayload::from_payload(UdpParser::payload(&buf)) {
                quacker.lock().unwrap().handle_discover_ack(disc);
            } else {
                warn!("Received non-discovery packet from proxy");
                quacker.lock().unwrap().handle_reset();
            }
            continue; // skip packets from proxy
        }

        // Update base connection identifier for sending discovery
        // to proxy. Identify by first UDP connection.
        {
            let addr_key = UdpParser::parse_addr_key(&buf);
            let mut quacker = quacker.lock().unwrap();
            if quacker.base_stoc != Some(addr_key) {
                if quacker.base_stoc.is_some() {
                    info!("Received new base connection: {} (old: {})",
                          addr_key.iter()
                                  .map(|b| format!("{:02x}", b))
                                  .collect::<String>(),
                          quacker.base_stoc.unwrap().iter()
                                               .map(|b| format!("{:02x}", b))
                                               .collect::<String>());
                } else {
                    info!("Received base connection: {}",
                          addr_key.iter()
                                  .map(|b| format!("{:02x}", b))
                                  .collect::<String>());
                }
                // Direction is incoming, so this packet is from the server.
                quacker.base_stoc = Some(addr_key);
                // Discovery packet should be sent at next quack interval.
                quacker.awaiting_disc_ack = true;
                // For the first packet, send a discovery
                // Send 2 dups to account for random loss
                quacker.send_discovery(&addr_key, 3).await;
            }
        }

        // Otherwise parse the identifier and insert it into the quack.
        if n != (BUFFER_SIZE as _) {
            trace!("underfilled buffer: {} < {}", n, BUFFER_SIZE);
            continue;
        }
        let id = UdpParser::parse_identifier(&buf, identifier_func.clone());
        trace!("insert {} ({:#10x})", id, id);
        {
            let mut q = quacker.lock().unwrap();
            let time_ms = current_time_ms();
            if q.insert(time_ms, id) {
                debug!("quack {}", q.get_quack().count());
            }
            drop(q);
        }
    }
    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<(), String> {
    env_logger::init();

    let args = Cli::parse();
    debug!("interface={} threshold={}", args.interface, args.threshold);
    debug!(
        "frequency_ms={:?} frequency_pkts={:?} target_addr={:?}",
        args.frequency_ms, args.frequency_pkts, args.target_addr
    );

    // Start the sidekick.
    let sc = Sidekick::new(&args.interface, args.threshold, args.target_addr.clone());

    // Handle a snapshotted quACK at the specified frequency.
    if args.frequency_ms > 0 {
        let sc = Arc::new(Mutex::new(sc));
        let (sendsock, rx) = Sidekick::start(sc.clone()).await?;
        info!("quACKing to {:?}", args.target_addr);
        send_quacks(sc, rx, sendsock, args.target_addr, args.frequency_ms).await;
    } else if args.frequency_pkts > 0 {
        let quacker = Arc::new(Mutex::new(UdpQuacker::new(
            args.threshold, args.frequency_pkts, args.frequency_ms, args.target_addr)));
        start_sniffer(quacker, &args.interface).await.unwrap();
    }
    Ok(())
}
