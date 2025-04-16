# real-world

## Setup

Install dependencies for cross-compilation.

```
rustup target add aarch64-unknown-linux-gnu
sudo apt install gcc-aarch64-linux-gnu
```

Add the following to `~/.cargo/config.toml`:

```
[target.aarch64-unknown-linux-gnu]
linker = "aarch64-linux-gnu-gcc"
```

## Build

Cross-compile the proxy binaries for the Pi.

```
export SIDEKICK_HOME=$HOME/sidekick-downloads
cd $SIDEKICK_HOME/proxy
cargo b --release --bin bridge --target aarch64-unknown-linux-gnu
cargo b --release --bin sidekick --target aarch64-unknown-linux-gnu
```

You can find the binary in `./target/aarch64-unknown-linux-gnu/release/`.
