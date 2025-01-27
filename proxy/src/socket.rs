use libc::*;
use log::debug;
use std::ffi::CString;
use crate::BUFFER_SIZE;

/// Structure representing a raw socket.
#[derive(Debug, Clone)]
pub struct Socket {
    /// File descriptor for read/write ops
    pub fd: i32,
    /// Interface name (e.g., "eth0")
    pub interface: String,
    /// Interface name (e.g., "eth0") as CString
    interface_c: CString,
    /// Caller-provided identifier that received packets
    /// will be marked with; generally an index in an array
    pub id: u16,
}

/// Wrapper for sockaddr_ll
/// See https://man7.org/linux/man-pages/man7/packet.7.html
pub struct SockAddr {}

impl SockAddr {
    pub fn new_sockaddr_ll() -> sockaddr_ll {
        sockaddr_ll {
            sll_family: 0,
            sll_protocol: 0,
            sll_ifindex: 0,
            sll_hatype: 0,
            sll_pkttype: 0,
            sll_halen: 0,
            sll_addr: [0; 8],
        }
    }
}

impl Socket {
    /// Create a raw socket and bind it to a specific interface.
    pub fn new(interface: String, id: u16) -> Result<Self, String> {
        let protocol = (ETH_P_ALL as i16).to_be() as c_int;
        let fd = unsafe { socket(AF_PACKET, SOCK_RAW, protocol) };
        if fd < 0 {
            Err(format!("socket: {}", fd))
        } else {
            debug!("opened socket with fd={}, interface={}, id={}", fd, interface, id);
            let sock = Self {
                fd,
                interface: interface.clone(),
                interface_c: CString::new(interface).unwrap(),
                id,
            };
            sock.bind(protocol)?;
            sock.set_promiscuous()?;
            Ok(sock)
        }
    }

    /// Bind to a specific interface.
    fn bind(&self, protocol: c_int) -> Result<(), String> {
        debug!("binding the socket to interface={}", self.interface);
        let res = unsafe {
            setsockopt(
                self.fd,
                SOL_SOCKET,
                SO_BINDTODEVICE,
                self.interface_c.as_ptr() as _,
                (self.interface.len() + 1) as _,
            )
        };
        if res < 0 {
            return Err(format!("setsockopt: {}", res));
        }
        let addr = sockaddr_ll {
            sll_family: AF_PACKET as u16,
            sll_protocol: protocol as u16,
            sll_ifindex: unsafe { if_nametoindex(self.interface_c.as_ptr()) } as i32,
            sll_hatype: 0,
            sll_pkttype: 0,
            sll_halen: 0,
            sll_addr: [0; 8],
        };
        let addr_ptr = (&addr) as *const sockaddr_ll;
        let addr_len = std::mem::size_of::<sockaddr_ll>();
        let res = unsafe { bind(self.fd, addr_ptr as _, addr_len as u32) };
        if res < 0 {
            return Err(format!("setsockopt: {}", res));
        }
        Ok(())
    }

    /// Set the network card in promiscuous mode.
    pub fn set_promiscuous(&self) -> Result<(), String> {
        debug!("setting {} to promiscuous mode", self.interface);
        let mut ethreq = ifreq {
            ifr_name: [0; IF_NAMESIZE],
            ifr_ifru: __c_anonymous_ifr_ifru { ifru_flags: 0 },
        };
        assert!(self.interface.len() <= IF_NAMESIZE); // <?
        ethreq.ifr_name[..self.interface.len()].clone_from_slice(
            &self
                .interface_c
                .as_bytes()
                .iter()
                .map(|&byte| byte as _)
                .collect::<Vec<_>>()[..],
        );
        if unsafe { ioctl(self.fd, SIOCGIFFLAGS, &ethreq) } == -1 {
            return Err(String::from("ioctl 1"));
        }
        unsafe { ethreq.ifr_ifru.ifru_flags |= IFF_PROMISC as i16 };
        if unsafe { ioctl(self.fd, SIOCSIFFLAGS, &ethreq) } == -1 {
            return Err(String::from("ioctl 2"));
        }
        Ok(())
    }

    /// Receive a packet with up to `BUFFER_SIZE` bytes into `buf`, and
    /// fill in socket address information.
    /// This is a blocking operation.
    pub fn recvfrom(
        &self,
        addr: &mut sockaddr_ll,
        buf: &mut [u8; BUFFER_SIZE],
    ) -> Result<isize, String> {
        let mut socklen = std::mem::size_of::<sockaddr_ll>() as u32;
        // wrapping our own libc functions because nix-rust is buggy:
        // https://github.com/nix-rust/nix/pull/1896
        let n = unsafe {
            recvfrom(
                self.fd,
                buf.as_ptr() as *mut c_void,
                buf.len(),
                0,
                (addr as *mut sockaddr_ll) as _,
                &mut socklen,
            )
        };
        if n < 0 {
            let errno = unsafe { *libc::__errno_location() };
            return Err(format!("recv: {}", errno));
        }
        Ok(n)
    }

    /// Write `BUFFER_SIZE` bytes to buffer.
    /// This should ideally represent a single packet.
    pub fn send(&self, buf: &[u8; BUFFER_SIZE], nbytes: usize) -> Result<isize, String> {
        let n = unsafe { write(self.fd, buf.as_ptr() as *const c_void, nbytes) };
        if n < 0 {
            return Err(format!("write: {}", n));
        }
        Ok(n)
    }

}

impl Drop for Socket {
    fn drop(&mut self) {
        unsafe {
            // can fail if socket is already closed (this is fine)
            libc::close(self.fd);
        }
    }
}
