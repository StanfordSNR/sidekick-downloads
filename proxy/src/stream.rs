use crate::BUFFER_SIZE;
use crate::socket::{Socket, SockAddr};
use tokio::sync::mpsc;
use log::{error, debug, trace};

const CHANNEL_CAPACITY: usize = 100;

/// Complete packet data, tagged with the interface
/// it was received on.
/// The interface identifier should be the `id` field in
/// the socket struct and the index in the PacketStream
/// sockets array.
#[derive(Debug, Clone, PartialEq)]
pub struct Packet {
    pub iface: u16,
    pub data: [u8; BUFFER_SIZE],
    pub nbytes: isize,
}

impl Packet {
    /// Initialize packet received on `iface` with empty data.
    pub fn new(iface: u16) -> Self {
        Self { iface, data: [0u8; BUFFER_SIZE], nbytes: 0 }
    }
}

/// Provides the abstraction of a stream between two Sockets.
/// Sends packets through the `mpsc` channel, tagged with the
/// ID of the socket that the packet was received on.
/// The socket ID is the index in the `sockets` array and
/// corresponds to the `id` field in the Socket struct.
pub struct PacketStream {
    pub receiver: mpsc::Receiver<Packet>,
    pub sockets: [Socket; 2],
}

impl PacketStream {
    /// Open sockets and mpsc channel, start polling packets
    pub fn new(interface1: String, interface2: String) -> Self {
        let (tx, rx) = mpsc::channel(CHANNEL_CAPACITY);
        let socket1 = Socket::new(interface1, 0).unwrap();
        let socket2 = Socket::new(interface2, 1).unwrap();
        tokio::spawn(poll_packets(socket1.clone(), tx.clone()));
        tokio::spawn(poll_packets(socket2.clone(), tx));
        debug!("Created PacketStream between interfaces {}, {}", socket1.interface, socket2.interface);
        PacketStream {
            receiver: rx,
            sockets: [socket1, socket2],
        }
    }

    /// Receive a message (tagged packet) from the channel
    pub async fn recv(&mut self) -> Option<Packet> {
        self.receiver.recv().await
    }

    /// Forward a packet received on one interface to the other.
    /// The packet's `iface` field is assumed to represent the interface
    /// it was originally received on, not the interface it will be forwarded
    /// to. The packet will be forwarded to interface `(iface + 1) % 2`.
    pub fn forward_packet(&self, packet: &Packet, nbytes: usize) {
        let iface = &self.sockets[((packet.iface + 1) % 2) as usize];
        trace!("Forwarding {} bytes from {} to {}",
               nbytes,
               &self.sockets[packet.iface as usize].interface,
               iface.interface);
        iface.send(&packet.data, nbytes).unwrap();
    }
}

/// Poll packets from `socket` and transfer them to the mpsc channel.
async fn poll_packets(socket: Socket, tx: mpsc::Sender<Packet>) {
    let mut addr = SockAddr::new_sockaddr_ll();
    debug!("Start polling packets for {} (id: {}, fd: {})",
           socket.interface, socket.id, socket.fd);
    loop {
        let mut packet = Packet::new(socket.id);
        let nbytes = match socket.recvfrom(&mut addr, &mut packet.data) {
            Ok(nbytes) => {
                trace!("Received {} bytes on {}", nbytes, socket.interface);
                nbytes
            },
            Err(e) => {
                trace!("Failed to rx on {}: {:?}", socket.interface, e);
                continue;
            },
        };
        packet.nbytes = nbytes;
        assert!(packet.nbytes > 0, "packet.nbytes={}", packet.nbytes);
        match tx.send(packet).await {
            Ok(_) => trace!("Notified of {} bytes on {}", nbytes, socket.interface),
            Err(e) => error!("Error on mpsc send {:?}", e),
        }
    }
}
