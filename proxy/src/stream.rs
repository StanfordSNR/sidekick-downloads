use tokio::sync::mpsc;
use log::{error, debug, trace};
use sidekick_utils::socket::{Socket, SockAddr};
use sidekick_utils::BUFFER_SIZE;
use libc::sockaddr_ll;

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
    pub sockets: [ProxySocket; 2],
}

impl PacketStream {
    /// Open sockets and mpsc channel, start polling packets
    pub fn new(client_iface: String, server_iface: String) -> Self {
        let (tx, rx) = mpsc::channel(CHANNEL_CAPACITY);
        let socket1 = ProxySocket::new(client_iface, 0, SocketType::Client).unwrap();
        let socket2 = ProxySocket::new(server_iface, 1, SocketType::Server).unwrap();
        tokio::spawn(poll_packets(socket1.clone(), tx.clone()));
        tokio::spawn(poll_packets(socket2.clone(), tx));
        debug!("Created PacketStream between interfaces {}, {}", socket1.interface(), socket2.interface());
        PacketStream {
            receiver: rx,
            sockets: [socket1, socket2],
        }
    }

    /// Returns identifier of the interface that was tagged as server on construction
    pub fn server_iface(&self) -> u16 {
        debug_assert!(self.sockets[1].socktype() == SocketType::Server);
        1
    }

    /// Returns identifier of interface that was tagged as client on construction
    pub fn client_iface(&self) -> u16 {
        debug_assert!(self.sockets[0].socktype() == SocketType::Client);
        0
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
               self.sockets[packet.iface as usize].interface(),
               iface.interface());
        iface.send(&packet.data, nbytes).unwrap();
    }

    /// Send `buf` to the specified interface
    pub fn send(&self, buf: &[u8; BUFFER_SIZE], nbytes: usize, iface: u16) {
        let iface = &self.sockets[iface as usize];
        trace!("Sending {} bytes to {}",
               nbytes,
               iface.interface());
        iface.send(buf, nbytes).unwrap();
    }
}

/// Poll packets from `socket` and transfer them to the mpsc channel.
async fn poll_packets(socket: ProxySocket, tx: mpsc::Sender<Packet>) {
    let mut addr = SockAddr::new_sockaddr_ll();
    debug!("Start polling packets for {} (id: {}, fd: {})",
           socket.interface(), socket.id(), socket.fd());
    loop {
        let mut packet = Packet::new(socket.id());
        let nbytes = match socket.recvfrom(&mut addr, &mut packet.data) {
            Ok(nbytes) => {
                trace!("Received {} bytes on {}", nbytes, socket.interface());
                nbytes
            },
            Err(e) => {
                trace!("Failed to rx on {}: {:?}", socket.interface(), e);
                continue;
            },
        };
        packet.nbytes = nbytes;
        assert!(packet.nbytes > 0, "packet.nbytes={}", packet.nbytes);
        match tx.send(packet).await {
            Ok(_) => trace!("Notified of {} bytes on {}", nbytes, socket.interface()),
            Err(e) => error!("Error on mpsc send {:?}", e),
        }
    }
}

/// Caller-provided tag for a socket
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SocketType {
    Client,
    Server,
    None
}

/// Socket + metadata required by the sidekick proxy
#[derive(Debug, Clone)]
pub struct ProxySocket {
    /// Socket for read/write ops
    socket: Socket,
    /// Caller-provided identifier that received packets
    /// will be marked with; generally an index in an array
    id: u16,
    /// Caller-provided tag; may be useful for interpreting directionality
    socktype: SocketType,
}

impl ProxySocket {
    pub fn new(interface: String, id: u16,
               socktype: SocketType) -> Result<Self, String> {
        let socket = Socket::new(interface)?;
        socket.set_promiscuous()?;
        Ok(Self {
            socket,
            id,
            socktype,
        })
    }

    pub fn interface(&self) -> &String {
        &self.socket.interface
    }

    pub fn send(&self, buf: &[u8; BUFFER_SIZE], nbytes: usize) -> Result<isize, String> {
        self.socket.send(buf, nbytes)
    }

    pub fn recvfrom(
        &self,
        addr: &mut sockaddr_ll,
        buf: &mut [u8; BUFFER_SIZE],
    ) -> Result<isize, String> {
        self.socket.recvfrom(addr, buf)
    }

    pub fn fd(&self) -> i32 {
        self.socket.fd
    }

    pub fn socktype(&self) -> SocketType {
        self.socktype.clone()
    }

    pub fn id(&self) -> u16 {
        self.id
    }
}