use clap::Parser;
use log::trace;
use flexi_logger::{Logger, WriteMode, FileSpec};

use proxy::stream::PacketStream;

#[derive(Parser)]
struct Cli {
    /// Interface 1 to listen on e.g., `eth1`.
    #[arg(long, short = 'o')]
    client_interface: String,
    /// Interface 2 to listen on e.g., `eth2`.
    #[arg(long, short = 'i')]
    server_interface: String,
    /// Logfile to write rust logs to (optional)
    /// This should be set for loglevel = TRACE. Excessively logging to
    /// stdout/stderr can interfere with Mininet's packet buffers.
    #[arg(long, short = 'f')]
    logfile: Option<String>,
}


#[tokio::main]
async fn main() {
    let args = Cli::parse();
    if let Some(logfile) = args.logfile {
        Logger::try_with_env_or_str("error").unwrap()
                                            .log_to_file(
                                                FileSpec::try_from(&logfile)
                                                    .expect(&format!("Cannot open {} for logging", logfile))
                                            ).write_mode(WriteMode::BufferAndFlush)
                                             .start()
                                             .unwrap();
    } else {
        env_logger::init();
    }
    let mut packet_stream = PacketStream::new(
        args.client_interface.clone(),
        args.server_interface.clone(),
    );
    eprintln!(
        "Ready to bridge between {} and {}",
        args.client_interface, args.server_interface
    );
    while let Some(packet) = packet_stream.receiver.recv().await {
        trace!("Received packet on mpsc: {}", packet.iface);
        packet_stream.forward_packet(&packet, packet.nbytes as usize);
    }
}