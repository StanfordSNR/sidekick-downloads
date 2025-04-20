use std::collections::VecDeque;

use log::debug;

use sidekick_utils::socket::Socket;
use sidekick_utils::BUFFER_SIZE;

pub struct SockSendBuffer {
    // Raw socket
    sock: Socket,
    eth_header: [u8; 14],
    buf: [u8; BUFFER_SIZE],

    // Dejitter buffer
    /// The seqno of the first IP datagram in the buffer
    next_seqno: u32,
    /// Max number of packets in the dejitter buffer
    capacity: u32,
    /// Length capacity at all times
    buffer: VecDeque<Option<Vec<u8>>>,
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

impl SockSendBuffer {
    pub fn new(
        sock: Socket, src_mac: String, dst_mac: String, capacity: u32,
    ) -> Result<Self, String> {
        let mut eth_header = [0u8; 14];
        eth_header[0..6].copy_from_slice(&parse_mac(&dst_mac)?[..]);
        eth_header[6..12].copy_from_slice(&parse_mac(&src_mac)?[..]);
        eth_header[12] = 0x08;
        eth_header[13] = 0x00;

        Ok(Self {
            sock,
            eth_header,
            buf: [0u8; BUFFER_SIZE],
            next_seqno: 0,
            capacity,
            buffer: VecDeque::from(vec![None; capacity as usize]),
        })
    }

    pub fn buffer_and_send(
        &mut self, seqno: u32, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        // Drop packets that are way too stale
        if seqno < self.next_seqno {
            debug!("[receiver] drop {} < {} below dejitter buffer range",
                seqno, self.next_seqno);
            return Ok(());
        }

        // Pop packets from the buffer until this seqno is in range
        while seqno >= self.next_seqno + self.capacity {
            self.pop_and_send()?;
        }

        // Add the packet to the buffer
        debug!("[receiver] buffer {}", seqno);
        let index = (seqno - self.next_seqno) as usize;
        self.buffer[index] = Some(ip_datagram);

        // Send packets if we can
        while self.buffer.front().unwrap().is_some() {
            let sent = self.pop_and_send()?;
            assert!(sent);
        }
        Ok(())
    }

    /// Returns whether a packet was sent.
    fn pop_and_send(&mut self) -> Result<bool, String> {
        let sent = if let Some(ip_datagram) = self.buffer.pop_front().unwrap() {
            self.send(self.next_seqno, ip_datagram)?;
            true
        } else {
            false
        };
        self.buffer.push_back(None);
        self.next_seqno += 1;
        Ok(sent)
    }

    pub fn send(
        &mut self, seqno: u32, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        let len = 14 + ip_datagram.len();
        self.buf[0..14].copy_from_slice(&self.eth_header);
        self.buf[14..14+ip_datagram.len()].copy_from_slice(ip_datagram.as_slice());
        debug!("[receiver] send {} ({} bytes)", seqno, len);
        self.sock.send(&self.buf, len)?;
        Ok(())
    }
}
