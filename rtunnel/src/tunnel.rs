use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;

use log::{trace, debug};
use tokio::net::UdpSocket;
use sidekick_utils::socket::Socket;
use sidekick_utils::BUFFER_SIZE;

use crate::ack::{BlockAck, BLOCK_SIZE};
use crate::net::Packet;

struct CachedItem {
    datagram: Vec<u8>,
    num_retx: usize,
}

impl CachedItem {
    fn new(datagram: Vec<u8>) -> Self {
        Self {
            datagram,
            num_retx: 0,
        }
    }
}

pub struct Tunnel {
    // Network parameters
    sock: Socket,
    conn: Arc<UdpSocket>,
    send_addr: SocketAddr,
    eth_header: [u8; 14],

    // Sender
    next_seqno: u32,
    /// Sent packets waiting for an ACK
    cache: HashMap<u32, CachedItem>,

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
            cache: HashMap::with_capacity(BLOCK_SIZE as usize),
            ack: BlockAck::new(),
        })
    }

    // unencapsulated packets
    pub async fn handle_inner_packet(
        &mut self, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        // if there's too many unacked packets, drop it
        if self.cache.len() >= (BLOCK_SIZE as usize) {
            debug!("dropping datagram");
            return Ok(());
        }

        // else encapsulate the packet and forward it
        let mut buf = [0u8; BUFFER_SIZE];
        let packet = Packet::Outer {
            seqno: self.next_seqno,
            ip_datagram,
    };
        let len = packet.serialize(&mut buf);
        trace!("sending {} outer bytes to {:?}", 42 + len, self.send_addr);
        debug!("send {}", self.next_seqno);
        self.conn.send_to(&buf[..len], self.send_addr).await.unwrap();

        // and store the encapsulated packet
        self.cache.insert(self.next_seqno, CachedItem::new(buf[..len].to_vec()));
        self.next_seqno += 1;
        Ok(())
    }

    // block ack
    pub async fn handle_block_ack(
        &mut self, ack: BlockAck,
    ) -> Result<(), String> {
        // remove everything that was acked from the cache
        let mut block = ack.block;
        let mut seqno = ack.seqno - BLOCK_SIZE;
        let mut max_acked = 0;
        let mut retx = vec![];
        while block != 0 {
            if block & 1 == 1 {
                if self.cache.remove(&seqno).is_some() {
                    debug!("evict {}", seqno);
                }
                max_acked = seqno;
            } else {
                retx.push(seqno);
            }
            block >>= 1;
            seqno += 1;
        }

        // retransmit anything that wasn't acked
        for seqno in retx.into_iter().take_while(|&seqno| seqno < max_acked) {
            if let Some(item) = self.cache.get_mut(&seqno) {
                debug!("retransmit {}", seqno);
                self.conn.send_to(&item.datagram[..], self.send_addr).await.unwrap();
                item.num_retx += 1;
            }
        }
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
        debug!("recv {}", seqno);
        trace!("sending {} inner bytes to {}", len, self.sock.interface);
        self.sock.send(&buf, len)?;
        Ok(())
    }
}
