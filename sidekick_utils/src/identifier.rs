use std::hash::{DefaultHasher, Hash, Hasher};

pub type Identifier = u32;

#[derive(Debug, Clone, Copy)]
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
    pub fn to_id(self, packet_data: &[u8]) -> Identifier {
        match self {
            IdentifierFunc::FirstByte => packet_data[0] as u32,
            IdentifierFunc::FixedOffset(index) => u32::from_be_bytes([
                packet_data[index],
                packet_data[index + 1],
                packet_data[index + 2],
                packet_data[index + 3],
            ]),
            IdentifierFunc::HashAtOffset(index) => {
                // NOTE: Optimize performance if we're actually using this
                // identifier function, such as by caching the hasher.
                let mut hasher = DefaultHasher::new();
                packet_data[index..].hash(&mut hasher);
                hasher.finish() as u32
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_first_byte_function() {
        let f = IdentifierFunc::FirstByte;
        assert_eq!(f.to_id(&[0]), 0);
        assert_eq!(f.to_id(&[1]), 1);
        assert_eq!(f.to_id(&[255]), 255);
        assert_eq!(f.to_id(&[12, 34, 56, 78]), 12, "multiple data bytes");
    }

    #[test]
    fn test_fixed_offset_function() {
        let no_offset = IdentifierFunc::FixedOffset(0);
        assert_eq!(no_offset.to_id(&[0, 0, 0, 0]), 0);
        assert_eq!(no_offset.to_id(&[0, 0, 0, 0x78]), 0x78);
        assert_eq!(no_offset.to_id(&[0x12, 0x34, 0x56, 0x78]), 0x12345678);
        assert_eq!(no_offset.to_id(&[0, 0x12, 0x34, 0x56, 0x78]), 0x123456);

        let with_offset = IdentifierFunc::FixedOffset(2);
        assert_eq!(with_offset.to_id(&[10, 10, 0, 0, 0, 0]), 0);
        assert_eq!(with_offset.to_id(&[10, 10, 0, 0, 0, 0x78]), 0x78);
        assert_eq!(
            with_offset.to_id(&[10, 10, 0x12, 0x34, 0x56, 0x78]),
            0x12345678
        );
        assert_eq!(
            with_offset.to_id(&[10, 10, 0, 0x12, 0x34, 0x56, 0x78]),
            0x123456
        );
    }

    #[test]
    fn test_hash_at_offset_function() {
        let no_offset = IdentifierFunc::HashAtOffset(0);
        let id1 = no_offset.to_id(&[0, 0, 0, 0]);
        let id2 = no_offset.to_id(&[0x12, 0x34, 0x56, 0x78]);
        let id3 = no_offset.to_id(&[0, 0x12, 0x34, 0x56, 0x78]);
        let id4 = no_offset.to_id(&[0, 0x12, 0x34, 0x56]);
        assert_ne!(id1, 0, "ids are hashed");
        assert_ne!(id2, 0x12345678, "ids are hashed");
        assert_ne!(id3, 0x123456, "ids are hashed");
        assert_ne!(id4, 0x123456, "ids are hashed");
        assert_ne!(id1, id2, "hashes are unique enough");
        assert_ne!(id1, id3, "hashes are unique enough");
        assert_ne!(id1, id4, "hashes are unique enough");
        assert_ne!(id2, id3, "hashes are unique enough");
        assert_ne!(id2, id4, "hashes are unique enough");
        assert_ne!(id3, id4, "hashes are unique enough");

        let with_offset = IdentifierFunc::HashAtOffset(2);
        assert_eq!(with_offset.to_id(&[10, 10, 0, 0, 0, 0]), id1);
        assert_eq!(with_offset.to_id(&[10, 10, 0x12, 0x34, 0x56, 0x78]), id2);
        assert_eq!(with_offset.to_id(&[10, 10, 0, 0x12, 0x34, 0x56, 0x78]), id3);
        assert_eq!(with_offset.to_id(&[10, 10, 0, 0x12, 0x34, 0x56]), id4);
    }
}
