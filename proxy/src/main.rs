use clap::Parser;
use log::{debug, info, trace, error};

mod socket;
use socket::{SockAddr, Socket};

#[derive(Parser)]
struct Cli {
    /// Interface 1 to listen on e.g., `eth1`.
    #[arg(long, short = 'o')]
    client_interface: String,
    /// Interface 2 to listen on e.g., `eth2`.
    #[arg(long, short = 'i')]
    server_interface: String,
}

fn main() {
    env_logger::init();
    let args = Cli::parse();
    debug!(
        "Echoing between {} and {}",
        args.client_interface, args.server_interface
    );

    let iface_1 = Socket::new(args.client_interface).unwrap();
    let iface_2 = Socket::new(args.server_interface).unwrap();
    let ifaces = vec![iface_1, iface_2];
    let mut buffer = [0; socket::BUFFER_SIZE];
    let mut addr = SockAddr::new_sockaddr_ll();
    info!("listening for packets");

    loop {
        for i in 0..ifaces.len() {
            let iface = &ifaces[i];
            let res = iface.recvfrom(
                &mut addr,
                &mut buffer,
            );
            if res.is_err() {
                continue;
            }
            let n = res.unwrap();
            trace!("received {} bytes on {:?}", n, iface);

            let iface = &ifaces[(i + 1) % ifaces.len()];
            let res = iface.send(&buffer, n.try_into().unwrap());
            if res.is_err() {
                continue;
            }
            let n = res.unwrap();
            trace!("sent {} bytes on {:?}", n, iface);
        }
    }
}

