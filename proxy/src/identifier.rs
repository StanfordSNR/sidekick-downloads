pub type Identifier = u32;

pub enum IdentifierFunc {
    /// Takes the first byte as the identifier
    FirstByte,
    /// Takes the first four bytes at the fixed packet offset as the big-endian
    /// u32 identifier
    FixedOffset(usize),
    /// Hashes the bytes after the fixed packet offset, typically the UDP
    /// payload, as the identifier
    HashAtOffset(usize),
}

impl IdentifierFunc {
    pub fn to_id(&self, packet_data: &[u8]) -> Identifier {
        match self {
            IdentifierFunc::FirstByte => unimplemented!(),
            IdentifierFunc::FixedOffset(index) => unimplemented!(),
            IdentifierFunc::HashAtOffset(index) => unimplemented!(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_first_byte_function() {
        unimplemented!()
    }

    #[test]
    fn test_fixed_offset_function() {
        unimplemented!()
    }

    #[test]
    fn test_hash_at_offset_function() {
        unimplemented!()
    }
}
