use clap::Parser;
use flexi_logger::{Logger, WriteMode, FileSpec};
use std::{fs::File, path::Path};
use proxy::Sidekick;
use proxy::pin_to_cpu;

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
    /// Capacity of the QUACK cache. Like a flow control window size.
    #[arg(long, short = 'c', default_value_t = 65536)]
    cache_capacity: usize,
    /// Whether to set the cache capacity in packets, instead of bytes (default).
    #[arg(long)]
    cache_capacity_pkts: bool,
    /// Max quACK threshold for initializing the power table.
    #[arg(long, default_value_t = 40)]
    max_threshold: usize,
    /// Logfile to write rust logs to (optional)
    /// Must be a complete, valid path including directory.
    /// This should be set for loglevel = TRACE. Excessively logging to
    /// stdout/stderr can interfere with Mininet's packet buffers.
    #[arg(long, short = 'f')]
    logfile: Option<String>,
    /// CPU ID to pin process to, if any
    #[arg(long, default_value_t = 3)]
    cpu_id: usize,
    /// Whether to use `cset` to isolate the process on cpu_id
    /// Note that this should only be used if GRUB hasn't been
    /// updated with "isolcpus", which is a more reliable approach
    /// but requires changing boot parameters.
    /// This may fail entirely depending on what other processes
    /// are running, in which case updating GRUB is the only option.
    #[arg(long, default_value_t = false)]
    isol_cpu: bool,
}

#[tokio::main]
async fn main() {
    let args = Cli::parse();
    if let Some(logfile) = args.logfile {
        if !Path::new(&logfile).exists() {
            eprintln!("Creating logfile {}", logfile);
            let _ = File::create(&logfile).expect(&format!("Cannot create {} for logging", logfile));
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
    pin_to_cpu(args.cpu_id, args.isol_cpu);
    eprintln!(
        "Ready to start Sidekick with client {}; expecting server {}",
        args.client_interface, args.server_interface
    );
    quack::global_config_set_max_power_sum_threshold(args.max_threshold);
    let mut sidekick = Sidekick::new(
        &args.client_interface,
        &args.server_interface,
        args.quack_port,
        args.cache_capacity,
        args.cache_capacity_pkts,
    );
    sidekick.start().await;
}