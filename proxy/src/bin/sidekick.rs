use clap::Parser;
use flexi_logger::{Logger, WriteMode, FileSpec};

use proxy::Sidekick;

#[derive(Parser)]
struct Cli {
    /// Interface 1 to listen on e.g., `eth1`.
    #[arg(long, short = 'o', default_value_t = String::from("p1-eth0"))]
    client_interface: String,
    /// Interface 2 to listen on e.g., `eth2`.
    #[arg(long, short = 'i', default_value_t = String::from("p1-eth1"))]
    server_interface: String,
    /// UDP port to listen on for quACKs from the client.
    #[arg(long, default_value_t = 5252)]
    quack_port: u16,
    /// Threshold number of missing packets in the quACK.
    #[arg(long, short = 't', default_value_t = 20)]
    quack_threshold: usize,
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
    let mut sidekick = Sidekick::new(
        &args.client_interface,
        &args.server_interface,
        args.quack_port,
        args.quack_threshold,
    );
    sidekick.start().await;
}