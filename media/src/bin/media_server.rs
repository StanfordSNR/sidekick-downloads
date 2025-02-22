//! Receives dummy WebRTC messages on a UDP socket.
//!
//! Store the incoming packets in a buffer and play them as soon as the next
//! packet in the sequence is available. If it ever detects a loss i.e. a
//! packet is missing after 3 later packets have been received, send a NACK
//! back to the sender that contains the sequence number of the missing packet.
//!
//! On receiving a timeout packet (sequence number is the max u32 integer),
//! print packet statistics. Print the average, p95, and p99 latencies, where
//! the latencies are how long the packet stayed in the queue. Print histogram.
use std::io;
use std::sync::Arc;

use clap::Parser;
use log::{debug, trace};
use tokio::net::UdpSocket;
use tokio::time::{Duration, Instant};
use media::{TIMEOUT_SEQNO, PAYLOAD_SIZE};
use media::{Statistics, BufferedPackets, Packet};

#[derive(Parser)]
struct Cli {
    /// Port to listen on.
    #[arg(long, default_value_t = 5201)]
    port: u16,
    /// End-to-end RTT in ms, which is also how often to resend NACKs.
    #[arg(long)]
    rtt: u64,
    /// Whether to loop forever.
    #[arg(long = "loop")]
    should_loop: bool,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> io::Result<()> {
    env_logger::init();

    let args = Cli::parse();

    // Listen for incoming packets.
    let nack_frequency = Duration::from_millis(args.rtt);
    let sock = {
        let addr = format!("0.0.0.0:{}", args.port);
        let sock = UdpSocket::bind(addr).await.unwrap();
        Arc::new(sock)
    };
    loop {
        let mut stats = Statistics::new();
        let mut pkts = BufferedPackets::new();
        let mut payload = [0; PAYLOAD_SIZE];
        debug!("webrtc server is now listening");
        loop {
            let (len, addr) = sock.recv_from(&mut payload).await?;
            assert_eq!(len, PAYLOAD_SIZE);
            let packet = Packet::from_payload(&payload);
            trace!("received seqno {} ({} bytes)", packet.seqno, len);
            assert!(!packet.is_nack);
            if packet.seqno == TIMEOUT_SEQNO {
                debug!("timeout message received");
                break;
            }
            let now = Instant::now();
            pkts.recv_seqno(packet.seqno, now);
            while let Some(time_recv) = pkts.pop_seqno() {
                stats.add_value(now - time_recv);
            }
            for seqno in pkts.nacks_to_send(now, nack_frequency) {
                Packet::new_nack(seqno).fill_payload(&mut payload);
                sock.send_to(&payload, addr).await?;
            }
        }

        // Print statistics before exiting.
        stats.print_statistics();

        // Exit the loop if not set.
        if !args.should_loop {
            break;
        }

        // Process remaining timeout messages.
        tokio::time::sleep(Duration::from_secs(1)).await;
        while sock.try_recv(&mut payload).is_ok() {}
    }
    Ok(())
}
