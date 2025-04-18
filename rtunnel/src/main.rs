mod ack;
mod buffer;
mod net;
mod tunnel;

use std::net::SocketAddr;
use std::sync::Arc;

use clap::Parser;
use log::trace;
use flexi_logger::{Logger, WriteMode, FileSpec};
use tokio::task;
use tokio::sync::mpsc;
use tokio::net::UdpSocket;

use sidekick_utils::BUFFER_SIZE;
use sidekick_utils::socket::{SockAddr, Socket};
use crate::net::Packet;
use crate::tunnel::Tunnel;

const MPSC_CHANNEL_SIZE: usize = 100;

#[derive(Parser)]
struct Cli {
    /// Network interface for un-encapsulated datagrams.
    #[arg(long)]
    iface: String,
    /// IP of the proxy to send encapsulated datagrams.
    #[arg(long)]
    ip: String,
    /// Port to send AND receive encapsulated datagrams.
    #[arg(long)]
    port: u16,
    /// Hardcoded MAC address of the src (host) iface
    #[arg(long)]
    src_mac: String,
    /// Hardcoded MAC address of the dst iface
    #[arg(long)]
    dst_mac: String,
    /// Maximum number of times to try a retransmit before dropping the packet
    #[arg(long, default_value_t = 1000)]
    max_num_retx: usize,
    /// Logfile to write rust logs to (optional)
    /// This should be set for loglevel = TRACE. Excessively logging to
    /// stdout/stderr can interfere with Mininet's packet buffers.
    #[arg(long, short = 'f')]
    logfile: Option<String>,
}

async fn listen_sock(
    tx: mpsc::Sender<Packet>, sock: Socket,
) -> Result<(), String> {
    let mut addr = SockAddr::new_sockaddr_ll();
    let mut buf = [0u8; BUFFER_SIZE];
    loop {
        let len = sock.recvmsg(&mut addr, &mut buf)?;
        assert!(len > 0, "len={}", len);
        trace!("received {} inner bytes from {}", len, sock.interface);
        let packet = Packet::parse_inner(&buf[..len]);
        tx.send(packet).await.unwrap();
    }
}

async fn listen_conn(
    tx: mpsc::Sender<Packet>, conn: Arc<UdpSocket>,
) -> Result<(), String> {
    let mut buf = [0u8; BUFFER_SIZE];
    loop {
        let (len, addr) = conn.recv_from(&mut buf).await.unwrap();
        trace!("received {} outer bytes from {:?}", 42 + len, addr);
        let packet = Packet::parse_outer(&buf[..len]);
        tx.send(packet).await.unwrap();
    }
}

async fn handle_incoming(
    mut rx: mpsc::Receiver<Packet>, mut tunnel: Tunnel,
) -> Result<(), String> {
    while let Some(packet) = rx.recv().await {
        match packet {
            Packet::Inner { ip_datagram } => {
                tunnel.handle_inner_packet(ip_datagram).await?;
            }
            Packet::Outer { seqno, ip_datagram } => {
                tunnel.handle_outer_packet(seqno, ip_datagram).await?;
            }
            Packet::Ack(ack) => {
                tunnel.handle_block_ack(ack).await?;
            }
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let args = Cli::parse();

    // Setup logging
    if let Some(logfile) = args.logfile {
        Logger::try_with_env_or_str("error").unwrap()
            .log_to_file(FileSpec::try_from(&logfile).unwrap())
            .write_mode(WriteMode::BufferAndFlush)
            .start()
            .unwrap();
    } else {
        env_logger::init();
    }

    // Initialize producers to the socket loop
    let (tx, rx) = mpsc::channel(MPSC_CHANNEL_SIZE);
    let sock = {
        let tx = tx.clone();
        let sock = Socket::new(args.iface.clone())?;
        sock.set_promiscuous()?;
        let sock_clone = sock.clone();
        task::spawn(async move {
            listen_sock(tx, sock_clone).await.unwrap()
        });
        sock
    };
    let conn = {
        let recv_addr: SocketAddr =
            format!("0.0.0.0:{}", args.port).parse().unwrap();
        let conn = Arc::new(UdpSocket::bind(recv_addr).await.unwrap());
        let conn_clone = conn.clone();
        task::spawn(async move {
            listen_conn(tx, conn_clone).await.unwrap()
        });
        conn
    };

    // Initialize socket loop handler
    let send_addr: SocketAddr =
        format!("{}:{}", args.ip, args.port).parse().unwrap();
    let tunnel = Tunnel::new(
        sock, conn, send_addr, args.src_mac, args.dst_mac, args.max_num_retx,
    )?;
    eprintln!("Ready to proxy {} and {}:{}", args.iface, args.ip, args.port);
    handle_incoming(rx, tunnel).await?;
    Ok(())
}
