use log::debug;
use tokio::time::Duration;

/// Dejitter delay statistics.
pub struct Statistics {
    values: Vec<Duration>,
    num_spurious: usize,
}

impl Statistics {
    /// Create a new histogram for adding duration values.
    pub fn new() -> Self {
        Self { values: Vec::new(), num_spurious: 0 }
    }

    /// Add a new duration value.
    pub fn add_value(&mut self, value: Duration) {
        self.values.push(value);
    }

    /// Add a spurious retransmission.
    pub fn add_spurious(&mut self) {
        self.num_spurious += 1;
    }

    /// Print average, p95, and p99 latency statistics.
    pub fn print_statistics(&self, prefix: Option<String>) {
        let prefix = prefix.unwrap_or(String::new());
        let (len, values) = {
            let mut values = self.values.clone();
            if values.len() == 0 {
                values.push(Duration::from_millis(0));
            }
            values.sort();
            (values.len(), values)
        };
        eprintln!("{}Num Spurious: {}", prefix, self.num_spurious);
        eprintln!("{}Num Values: {}", prefix, len);
        eprintln!("{}Median: {:?}", prefix, values[(len as f64 * 0.50) as usize]);
        eprintln!("{}p95: {:?}", prefix, values[(len as f64 * 0.95) as usize]);
        eprintln!("{}p99: {:?}", prefix, values[(len as f64 * 0.99) as usize]);
        let values_raw = values
            .into_iter()
            .map(|duration| duration.as_secs() * 1000000000 + duration.subsec_nanos() as u64)
            .collect::<Vec<_>>();
        // Print 90% to 100% by 0.1%
        debug!(
            "{}Latencies (ns) = {:?}",
            prefix,
            (900..1001)
                .map(|percent| (percent as f64) / 1000.0)
                .map(|percent| ((len as f64) * percent) as usize)
                .map(|index| std::cmp::min(index, len - 1))
                .map(|index| values_raw[index])
                .collect::<Vec<_>>()
        );
        eprintln!(
            "{}Raw values = {:?}",
            prefix,
            self.values
                .iter()
                .map(|duration| duration.as_secs() * 1000000000 + duration.subsec_nanos() as u64)
                .collect::<Vec<_>>()
        );
    }
}