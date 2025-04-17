pub struct BlockAck {
    // Largest seqno received
    seqno: usize,
    // Default is 64 packets
    blocks: [u32; 2],
}
