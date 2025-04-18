use log::{trace, debug};

use sidekick_utils::socket::Socket;
use sidekick_utils::BUFFER_SIZE;

pub struct SockSendBuffer {
    // Raw socket
    sock: Socket,
    eth_header: [u8; 14],
    buf: [u8; BUFFER_SIZE],
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
        sock: Socket, src_mac: String, dst_mac: String,
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
        })
    }

    pub fn send(
        &mut self, seqno: u32, ip_datagram: Vec<u8>,
    ) -> Result<(), String> {
        let len = 14 + ip_datagram.len();
        self.buf[0..14].copy_from_slice(&self.eth_header);
        self.buf[14..14+ip_datagram.len()].copy_from_slice(ip_datagram.as_slice());
        debug!("recv {} ({} bytes)", seqno, len);
        trace!("sending {} inner bytes to {}", len, self.sock.interface);
        self.sock.send(&self.buf, len)?;
        Ok(())
    }
}
