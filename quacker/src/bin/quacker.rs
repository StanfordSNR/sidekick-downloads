use clap::Parser;
use log::{trace, debug, info, warn};
use flexi_logger::{Logger, WriteMode, FileSpec};
use std::fs::File;
use std::path::Path;
use std::net::{SocketAddr, Ipv4Addr};
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio::time::{self, Instant, Duration};

use sidekick_utils::{BUFFER_SIZE, ID_BUFFER_SIZE, ID_OFFSET};
use sidekick_utils::packet::{NUM_DISCOVERY_PKTS, DISCOVERY_FREQ_MS, CachePolicy};
use sidekick_utils::socket::{SockAddr, Socket};
use sidekick_utils::buffer::{UdpParser, Direction};
use sidekick_utils::identifier::IdentifierFunc;
use quacker::{Quacker, UdpQuacker, current_time_ms};


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
    /// Whether to use the RIBLT quACK.
    #[arg(long)]
    riblt: bool,
    /// Whether to use the optimistic cache policy (default is sidekick-reset).
    #[arg(long)]
    optimistic: bool,
    /// Logfile to write rust logs to (optional)
    /// Must be a complete, valid path including directory.
    /// This should be set for loglevel = TRACE. Excessively logging to
    /// stdout/stderr can interfere with Mininet's packet buffers.
    #[arg(long, short = 'f')]
    logfile: Option<String>,
}

async fn send_quacks(
    quacker: Arc<Mutex<UdpQuacker>>,
    frequency_ms: u64,
) {
    assert!(frequency_ms > 0);
    let mut interval = time::interval(Duration::from_millis(frequency_ms));
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

async fn start_sniffer(
    quacker: Arc<Mutex<UdpQuacker>>,
    interface: &str,
) -> Result<(), String> {
    let identifier_func = IdentifierFunc::FixedOffset(ID_OFFSET);
    let recvsock = Socket::new(interface.to_string())?;
    recvsock.set_promiscuous()?;

    // Note the quack_addr is assumed to never change
    let quack_addr = quacker.lock().await.dst_addr();

    // Time of sending the last discovery packet
    let mut discovery_sent = Instant::now();

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
            quacker.lock().await.handle_sidekick_payload(UdpParser::payload(&buf, n));
            continue; // skip packets from proxy
        }

        // Update base connection identifier for sending discovery
        // to proxy. Identify by first UDP connection.
        {
            let addr_key = UdpParser::parse_addr_key(&buf);
            let mut quacker = quacker.lock().await;
            if quacker.base_stoc.is_none() {
                info!("Received base connection: {}",
                      addr_key.iter()
                              .map(|b| format!("{:02x}", b))
                              .collect::<String>());
                // For the first packet, send a discovery
                // Send multiple NUM_DISCOVERY_PKTS to account for random loss
                quacker.send_discovery(addr_key, NUM_DISCOVERY_PKTS);
                discovery_sent = Instant::now();
                continue;
            } else if quacker.awaiting_disc_ack &&
                    discovery_sent.elapsed() > Duration::from_millis(DISCOVERY_FREQ_MS) {
                quacker.send_discovery(addr_key, NUM_DISCOVERY_PKTS);
                discovery_sent = Instant::now();
                continue;
            } else if quacker.awaiting_disc_ack {
                // Don't process any stoc packets if the DiscoverAck is pending
                continue;
            }
        }

        // Otherwise parse the identifier and insert it into the quack.
        if n < (ID_BUFFER_SIZE as _) {
            warn!("underfilled buffer: {} < {}", n, ID_BUFFER_SIZE);
            continue;
        }
        let id = UdpParser::parse_identifier(&buf, identifier_func.clone());
        trace!("insert {} ({:#10x})", id, id);
        {
            let mut q = quacker.lock().await;
            let time_ms = current_time_ms();
            q.insert(time_ms, id);
            drop(q);
        }
    }
    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<(), String> {
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
    debug!("interface={} threshold={}", args.interface, args.threshold);
    debug!(
        "frequency_ms={:?} frequency_pkts={:?} target_addr={:?}",
        args.frequency_ms, args.frequency_pkts, args.target_addr
    );
    let cache_policy = if args.optimistic {
        CachePolicy::Optimistic
    } else {
        CachePolicy::SidekickReset
    };
    let quacker = Arc::new(Mutex::new(UdpQuacker::new(
        args.threshold, args.frequency_pkts, args.frequency_ms,
        args.target_addr, args.riblt, cache_policy)));
    if args.frequency_ms > 0 {
        let quacker = quacker.clone();
        tokio::task::spawn(async move {
            send_quacks(quacker, args.frequency_ms).await;
        });
    }
    start_sniffer(quacker, &args.interface).await.unwrap();
    Ok(())
}
