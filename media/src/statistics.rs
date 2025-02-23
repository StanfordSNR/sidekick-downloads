use log::info;
use tokio::time::Duration;

/// Dejitter delay statistics.
pub struct Statistics {
    values: Vec<Duration>,
}

impl Statistics {
    /// Create a new histogram for adding duration values.
    pub fn new() -> Self {
        Self { values: Vec::new() }
    }

    /// Add a new duration value.
    pub fn add_value(&mut self, value: Duration) {
        self.values.push(value);
    }

    /// Print average, p95, and p99 latency statistics.
    pub fn print_statistics(&self) {
        let (len, values) = {
            let mut values = self.values.clone();
            if values.len() == 0 {
                values.push(Duration::from_millis(0));
            }
            values.sort();
            (values.len(), values)
        };
        info!("Num Values: {}", len);
        info!("Median: {:?}", values[(len as f64 * 0.50) as usize]);
        info!("p95: {:?}", values[(len as f64 * 0.95) as usize]);
        info!("p99: {:?}", values[(len as f64 * 0.99) as usize]);
        let values_raw = values
            .into_iter()
            .map(|duration| duration.as_secs() * 1000000000 + duration.subsec_nanos() as u64)
            .collect::<Vec<_>>();
        // Print 90% to 100% by 0.1%
        info!(
            "Latencies (ns) = {:?}",
            (900..1001)
                .map(|percent| (percent as f64) / 1000.0)
                .map(|percent| ((len as f64) * percent) as usize)
                .map(|index| std::cmp::min(index, len - 1))
                .map(|index| values_raw[index])
                .collect::<Vec<_>>()
        );
        info!(
            "Raw values = {:?}",
            self.values
                .iter()
                .map(|duration| duration.as_secs() * 1000000000 + duration.subsec_nanos() as u64)
                .collect::<Vec<_>>()
        );
    }
}