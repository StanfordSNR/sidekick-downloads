use clap::Parser;
use log::{trace, info};

use proxy::stream::PacketStream;

#[derive(Parser)]
struct Cli {
    /// Interface 1 to listen on e.g., `eth1`.
    #[arg(long, short = 'o')]
    client_interface: String,
    /// Interface 2 to listen on e.g., `eth2`.
    #[arg(long, short = 'i')]
    server_interface: String,
}


#[tokio::main]
async fn main() {
    env_logger::init();
    let args = Cli::parse();
    let mut packet_stream = PacketStream::new(
        args.client_interface.clone(),
        args.server_interface.clone(),
    );
    info!(
        "Ready to bridge between {} and {}",
        args.client_interface, args.server_interface
    );
    while let Some(packet) = packet_stream.receiver.recv().await {
        trace!("Received packet on mpsc: {}", packet.iface);
        packet_stream.forward_packet(&packet, packet.nbytes as usize);
    }
}