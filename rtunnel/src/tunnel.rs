use std::net::SocketAddr;
use std::sync::Arc;

use tokio::net::UdpSocket;
use sidekick_utils::socket::Socket;

use crate::ack::BlockAck;

pub struct Tunnel {
    sock: Socket,
    conn: Arc<UdpSocket>,
}

impl Tunnel {
    pub fn new(sock: Socket, conn: Arc<UdpSocket>, send_addr: SocketAddr) -> Self {
        Self {
            sock,
            conn,
        }
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
        unimplemented!()
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
        unimplemented!()
    }
}
