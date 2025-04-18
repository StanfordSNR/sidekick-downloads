use std::net::SocketAddr;
use std::sync::Arc;

use log::debug;
use tokio::net::UdpSocket;
use sidekick_utils::socket::Socket;
use sidekick_utils::BUFFER_SIZE;

use crate::ack::BlockAck;
use crate::net::Packet;

const ETHERNET_HEADER_LEN: usize = 14;

pub struct Tunnel {
    // Network parameters
    sock: Socket,
    conn: Arc<UdpSocket>,
    send_addr: SocketAddr,
    eth_header: [u8; 14],

    // Sender
    next_seqno: u32,

    // Receiver
    ack: BlockAck,
}

fn parse_mac(mac_str: &str) -> Result<[u8; 6], String> {
    let parts: Vec<&str> = mac_str.split(':').collect();
    if parts.len() != 6 {
        return Err(format!("invalid MAC address: {}", mac_str));
    }
    let mut mac = [0u8; 6];
    for (i, part) in parts.iter().enumerate() {
        mac[i] = u8::from_str_radix(part, 16).map_err(|_|
            format!("invalid hex digit in MAC: {}", mac_str))?;
    }
    Ok(mac)
}

impl Tunnel {
    pub fn new(
        sock: Socket, conn: Arc<UdpSocket>, send_addr: SocketAddr,
        src_mac: String, dst_mac: String,
    ) -> Result<Self, String> {
        let mut eth_header = [0u8; 14];
        eth_header[0..6].copy_from_slice(&parse_mac(&dst_mac)?[..]);
        eth_header[6..12].copy_from_slice(&parse_mac(&src_mac)?[..]);
        eth_header[12] = 0x08;
        eth_header[13] = 0x00;
        Ok(Self {
            sock,
            conn,
            send_addr,
            eth_header,
            next_seqno: 0,
            ack: BlockAck::new(),
        })
    }

    // unencapsulated packets
    pub async fn handle_inner_packet(
        &mut self, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        // if there's too many unacked packets, drop it
        // else store the packet for retransmission
        let mut buf = [0u8; BUFFER_SIZE];
        let packet = Packet::Outer { seqno: self.next_seqno, ip_datagram };
        let len = packet.serialize(&mut buf);
        debug!("sending {} outer bytes to {:?}", 42 + len, self.send_addr);
        self.conn.send_to(&buf[..len], self.send_addr).await.unwrap();
        self.next_seqno += 1;
        Ok(())
    }

    // block ack
    pub async fn handle_block_ack(
        &mut self, ack: BlockAck,
    ) -> Result<(), String> {
        // remove acked packets from the cache
        // for unacked packets, retransmit and increase the counter
        // if the counter is at the max, discard it
        debug!("received block ack {:?}", ack);
        Ok(())
    }

    // encapsulated packets
    pub async fn handle_outer_packet(
        &mut self, seqno: u32, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        // update the block ack and send it
        let mut buf = [0u8; BUFFER_SIZE];
        self.ack.ack(seqno);
        let len = Packet::Ack(self.ack).serialize(&mut buf);
        self.conn.send_to(&buf[..len], self.send_addr).await.unwrap();

        // write the datagram to the raw socket, filling in the L2 headers
        let len = 14 + ip_datagram.len();
        buf[0..14].copy_from_slice(&self.eth_header);
        buf[14..14+ip_datagram.len()].copy_from_slice(ip_datagram.as_slice());
        debug!("sending {} inner bytes to {}", len, self.sock.interface);
        self.sock.send(&buf, len)?;
        Ok(())
    }
}
