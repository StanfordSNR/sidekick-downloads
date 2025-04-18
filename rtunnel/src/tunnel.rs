use std::net::SocketAddr;
use std::sync::Arc;

use log::debug;
use tokio::net::UdpSocket;
use sidekick_utils::socket::Socket;
use sidekick_utils::BUFFER_SIZE;

use crate::ack::BlockAck;

const ETHERNET_HEADER_LEN: usize = 14;

pub struct Tunnel {
    sock: Socket,
    conn: Arc<UdpSocket>,
    send_addr: SocketAddr,
    src_mac: [u8; 6],
    dst_mac: [u8; 6],
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
        Ok(Self {
            sock,
            conn,
            send_addr,
            src_mac: parse_mac(&src_mac)?,
            dst_mac: parse_mac(&dst_mac)?,
        })
    }

    // unencapsulated packets
    pub async fn handle_inner_packet(
        &mut self, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        // if there's too many unacked packets, drop it
        // else store the packet for retransmission

        // take the IP headers and payload
        // wrap it with its own header with only incrementing outer seqnos
        // send it as a UDP payload to conn
        debug!("sending {} bytes to {:?}", ip_datagram.len(), self.send_addr);
        self.conn.send_to(&ip_datagram[..], self.send_addr).await.unwrap();
        Ok(())
    }

    // block ack
    pub async fn handle_block_ack(
        &mut self, ack: BlockAck,
    ) -> Result<(), String> {
        // remove acked packets from the cache
        // for unacked packets, retransmit and increase the counter
        // if the counter is at the max, discard it
        unimplemented!()
    }

    // encapsulated packets
    pub async fn handle_outer_packet(
        &mut self, seqno: u32, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        // parse the custom header to get the outer seqno
        // update the block ack and send it
        // decapsulate the custom header and write to sock
        debug!("handling outer packet {} bytes", ip_datagram.len());
        let mut buf = [0u8; BUFFER_SIZE];
        buf[0..6].copy_from_slice(&self.dst_mac);
        buf[6..12].copy_from_slice(&self.src_mac);
        buf[12] = 0x08;
        buf[13] = 0x00;
        buf[14..14+ip_datagram.len()].copy_from_slice(ip_datagram.as_slice());
        self.sock.send(&buf, ip_datagram.len() + ETHERNET_HEADER_LEN)?;
        Ok(())
    }
}
