use log::{debug, info, trace, error};
use std::net::{Ipv4Addr, SocketAddr};
use std::sync::{Arc, Mutex};
use tokio::net::UdpSocket;
use tokio::sync::oneshot;

use sidekick_utils::{BUFFER_SIZE, ID_OFFSET};
use sidekick_utils::socket::{SockAddr, Socket};
use sidekick_utils::buffer::{UdpParser, Direction, AddrKey};
use sidekick_utils::identifier::IdentifierFunc;
use sidekick_utils::discovery::{DiscoveryPayload, DiscoveryOp};
use quack::{PowerSumQuack, PowerSumQuackU32};

#[derive(Clone)]
pub struct Sidekick {
    pub interface: String,
    pub threshold: usize,
    pub base_stoc: Option<AddrKey>, // base conn 4-tuple
    quack: PowerSumQuackU32,
    log: Vec<u32>,
    quack_addr: Option<SocketAddr>, // sidekick proxy's address
    pub awaiting_disc_ack: bool, // requested discovery, awaiting ack
}

impl Sidekick {
    /// Create a new sidekick.
    pub fn new(interface: &str, threshold: usize,
               quack_addr: Option<SocketAddr>) -> Self {
        Self {
            interface: interface.to_string(),
            threshold,
            base_stoc: None,
            quack: PowerSumQuackU32::new(threshold),
            log: vec![],
            quack_addr,
            awaiting_disc_ack: false,
        }
    }

    /// Insert a packet into the cumulative quACK. Should be used by quACK
    /// receivers, such as in the client code, with direct access to sent
    /// packets. Typically if this function is used, do not call start().
    pub fn insert_packet(&mut self, id: u32) {
        if self.threshold != 0 {
            self.quack.insert(id);
        }
    }

    /// Reset the sidekick state.
    pub fn reset(&mut self) {
        self.quack = PowerSumQuackU32::new(self.threshold);
        self.log = vec![];
    }

    /// Start the raw socket that listens to the specified interface and
    /// accumulates those packets in a quACK. If the sidekick is a quACK sender,
    /// only listens for incoming packets. If the sidekick is a quACK receiver,
    /// only listens for outgoing packets, and additionally logs the packet
    /// identifiers.
    /// Returns a channel that indicates when the first packet is sniffed.
    pub async fn start(
        sc: Arc<Mutex<Sidekick>>,
    ) -> Result<(UdpSocket, oneshot::Receiver<()>), String> {
        let identifier_func = IdentifierFunc::FixedOffset(ID_OFFSET);
        let interface = sc.lock().unwrap().interface.clone();
        let sock = Socket::new(interface.clone())?;
        let sendsock = UdpSocket::bind("0.0.0.0:0").await.unwrap();
        let my_port = sendsock.local_addr().unwrap().port();
        sock.set_promiscuous()?;

        // Creates the channel that indicates when the first packet is sniffed.
        let (tx, rx) = oneshot::channel();

        // Loop over received packets
        tokio::task::spawn_blocking(move || {
            info!("tapping socket on fd={} interface={}", sock.fd, interface);
            let mut buf: [u8; BUFFER_SIZE] = [0; BUFFER_SIZE];
            let mut addr = SockAddr::new_sockaddr_ll();
            let ip_protocol = (libc::ETH_P_IP as u16).to_be();
            let mut tx = Some(tx);
            while let Ok(n) = sock.recvfrom(&mut addr, &mut buf) {
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

                // If this is an incoming discovery packet from the proxy, handle it.
                {
                    let quack_addr = { sc.lock().unwrap().quack_addr };
                    // Note the quack_addr is assumed to never change
                    if let Some(quack_addr) = quack_addr {
                        if Ipv4Addr::from(UdpParser::parse_src_ip(&buf)) == quack_addr.ip() &&
                           u16::from_be_bytes(UdpParser::parse_src_port(&buf)) == quack_addr.port() {
                            Sidekick::handle_discover(&sc, &buf);
                            continue; // skip packets from proxy
                        }
                    }
                }

                // Update base connection identifier for sending discovery
                // to proxy. Identify by first UDP connection.
                {
                    let addr_key = UdpParser::parse_addr_key(&buf);
                    let mut sc = sc.lock().unwrap();
                    if sc.base_stoc != Some(addr_key) {
                        if sc.base_stoc.is_some() {
                            info!("Received new base connection: {} (old: {})",
                                  addr_key.iter()
                                          .map(|b| format!("{:02x}", b))
                                          .collect::<String>(),
                                  sc.base_stoc.unwrap().iter()
                                                       .map(|b| format!("{:02x}", b))
                                                       .collect::<String>());
                        } else {
                            info!("Received base connection: {}",
                                  addr_key.iter()
                                          .map(|b| format!("{:02x}", b))
                                          .collect::<String>());
                        }
                        // Direction is incoming, so this packet is from the server.
                        sc.base_stoc = Some(UdpParser::parse_addr_key(&buf));
                        // Reset the sidekick -- could be an update.
                        sc.reset();
                        // Discovery packet should be sent at next quack interval.
                        sc.awaiting_disc_ack = true;
                    }
                }

                // Reset the quack if the dst port is the one we are sending on.
                if UdpParser::parse_dst_port(&buf) == my_port {
                    sc.lock().unwrap().reset();
                    continue;
                }

                // Otherwise parse the identifier and insert it into the quack.
                if n != (BUFFER_SIZE as _) {
                    trace!("underfilled buffer: {} < {}", n, BUFFER_SIZE);
                    continue;
                }

                let id = UdpParser::parse_identifier(&buf,
                                                          identifier_func.clone());
                trace!("insert {} ({:#10x})", id, id);
                // TODO: filter by QUIC connection?
                {
                    let mut sc = sc.lock().unwrap();
                    if let Some(tx) = tx.take() {
                        tx.send(()).unwrap();
                    }
                    sc.insert_packet(id);
                }
            }
        });
        Ok((sendsock, rx))
    }

    /// Handle discovery packets from the proxy.
    /// Assumes that this packet is known to be a UDP packet from the proxy
    /// by source port and IP address.
    fn handle_discover(sc: &Arc<Mutex<Sidekick>>, buf: &[u8; BUFFER_SIZE]) {
        if let Some(disc) = DiscoveryPayload::from_payload(UdpParser::payload(&buf)) {
            if disc.op == DiscoveryOp::DiscoverAck {
                let mut sc = sc.lock().unwrap();
                if Some(disc.base_connection_stoc) == sc.base_stoc {
                    // Start aggregating quacks only after proxy is ready.
                    // May receive dup discovery ACKs; only initialize (reset)
                    // on first one.
                    if sc.awaiting_disc_ack {
                        sc.reset();
                        sc.awaiting_disc_ack = false;
                        info!("Received DiscoverACK from proxy");
                    }
                } else if sc.base_stoc.is_some() {
                    info!("Received DiscoverACK from proxy for old data: {} (expected: {})",
                            disc.base_connection_stoc.iter()
                                                     .map(|b| format!("{:02x}", b))
                                                     .collect::<String>(),
                            sc.base_stoc.unwrap().iter()
                                                 .map(|b| format!("{:02x}", b))
                                                 .collect::<String>());
                } else {
                    panic!("Received DiscoverACK from proxy before sending discovery");
                }
            } else {
                trace!("Received packet from proxy with op {:?}", disc.op);
            }
        } else {
            error!("Received non-discovery packet from proxy");
        }
    }

    /// Send discovery through `socket` to `addr`
    /// `base` is assumed to be the AddrKey of the base connection
    /// `socket` and `addr` are assumed to be the sidekick connection.
    ///
    /// Note: this will send `n` identical discovery packets. For n > 1, this increases
    /// the chance that a discovery reaches the proxy in the presence of random loss
    /// (duplicate discovery packets are no-ops).
    pub async fn send_discovery(socket: &UdpSocket, base: &AddrKey, addr: SocketAddr,
                                n: usize) {
        let bytes = bincode::serialize(
            &DiscoveryPayload::new(*base,
                DiscoveryOp::Discover)).unwrap();
        for i in 0..n {
            if socket.send_to(&bytes, addr).await.is_err() {
                error!("Failed to send {}th discovery packet", i);
                return;
            } else {
                info!("Sent discovery for sidekick base connection {}",
                      base.iter()
                          .map(|b| format!("{:02x}", b))
                          .collect::<String>());
            }
        }
    }

    /// Start the raw socket that listens to the specified interface and
    /// accumulates those packets in a quACK. If the sidekick is a quACK sender,
    /// only listens for incoming packets. If the sidekick is a quACK receiver,
    /// only listens for outgoing packets, and additionally logs the packet
    /// identifiers.
    /// Returns a channel that indicates when the first packet is sniffed.
    pub async fn start_frequency_pkts(
        &mut self,
        frequency_pkts: usize,
        sendaddr: std::net::SocketAddr,
    ) -> Result<(), String> {
        let identifier_func = IdentifierFunc::FixedOffset(ID_OFFSET);
        let recvsock = Socket::new(self.interface.clone())?;
        let sendsock = UdpSocket::bind("0.0.0.0:0").await.unwrap();
        let my_port = sendsock.local_addr().unwrap().port();
        recvsock.set_promiscuous()?;

        // Loop over received packets
        let mut buf: [u8; BUFFER_SIZE] = [0; BUFFER_SIZE];
        info!(
            "tapping socket on fd={} interface={}",
            recvsock.fd, self.interface
        );
        let mut addr = SockAddr::new_sockaddr_ll();
        let ip_protocol = (libc::ETH_P_IP as u16).to_be();
        let mut mod_count = 0;
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

            // Reset the quack if the dst port is the one we are sending on.
            if UdpParser::parse_dst_port(&buf) == my_port {
                self.reset();
                continue;
            }

            // Otherwise parse the identifier and insert it into the quack.
            if n != (BUFFER_SIZE as _) {
                trace!("underfilled buffer: {} < {}", n, BUFFER_SIZE);
                continue;
            }
            let id = UdpParser::parse_identifier(&buf, identifier_func.clone());
            debug!("insert {} ({:#10x})", id, id);
            // TODO: filter by QUIC connection?
            self.insert_packet(id);
            mod_count = (mod_count + 1) % frequency_pkts;
            if mod_count == 0 {
                let bytes = bincode::serialize(&self.quack).unwrap();
                trace!("quack {}", self.quack.count());
                sendsock.send_to(&bytes, sendaddr).await.unwrap();
            }
        }
        Ok(())
    }

    /// Snapshot the quACK.
    pub fn quack(&self) -> PowerSumQuackU32 {
        self.quack.clone()
    }
}
