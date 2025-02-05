# Setup

## Install a Linux kernel, if necessary.

If evaluating TCP BBRv2 or BBRv3, follow the instructions in
[BBRv3.md](https://github.com/ygina/sidekick-downloads/blob/main/deps/BBRV3.md)
to install a fork of the Linux kernel with these congestion control modules.

## Install Linux dependencies.

```
sudo apt-get update -y
sudo apt-get install -y autoconf libnfnetlink-dev  # pepsal
sudo apt-get install -y libnss3-tools  # certificates
sudo apt-get install -y python3-pip mininet  # mininet
sudo apt-get install -y python3-virtualenv  # plotting
sudo apt-get install -y cmake  # cloudflare quiche
sudo apt-get install -y libssl-dev  # picoquic
sudo apt-get install -y bridge-utils # emulation topology config
```

## Build the sidekick protocol binaries.

### Install Rust (if needed)

Install the Rust toolchain (instructions [here](https://www.rust-lang.org/tools/install)):

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
```

### Build the proxy

See [instructions](https://github.com/ygina/sidekick-downloads/blob/main/proxy/).

```
export SIDEKICK_HOME=$HOME/sidekick-downloads
cd $SIDEKICK_HOME/proxy
cargo build --bin bridge --release
cargo build --bin sidekick --release
```

### Build the client-side sniffer

The quack library needs nightly rust for unessential reasons.

```
export SIDEKICK_HOME=$HOME/sidekick-downloads
cd $SIDEKICK_HOME/deps
git clone git@github.com:ygina/quack.git
cd $SIDEKICK_HOME/quacker
rustup default nightly-2024-01-26
cargo build --release
```

## TCP Benchmarks

### Build and install PEPsal

Fetch the PEPsal source.

```
export SIDEKICK_HOME=$HOME/sidekick-downloads
cd $SIDEKICK_HOME/deps
git clone git@github.com:viveris/pepsal.git
```

Build and install PEPsal.

```
cd $SIDEKICK_HOME/deps
./build_deps.sh 1
```

Test that `pepsal` is on your path.

### Generate certificates

Generate certificates using Chromium scripts.

```
cd $SIDEKICK_HOME/deps/certs
./generate-certs.sh
mkdir -p "$HOME/.pki/nssdb"
certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n web -i out/2048-sha256-root.pem
openssl x509 -noout -pubkey < out/leaf_cert.pem | \
	openssl rsa -pubin -outform der | \
	openssl dgst -sha256 -binary | \
	openssl enc -base64
```

Check that the files `leaf_cert.pem`, `leaf_cert.pkcs8`, and `leaf_cert.key`
exist in `deps/certs/out/`.

## QUIC Benchmarks (Google)

Skip this section if not running QUIC benchmarks. It takes around an hour.

### Build and install Chromium QUIC

Fetch the Chromium source. (10 min)

```
export SIDEKICK_HOME=$HOME/sidekick-downloads
cd $SIDEKICK_HOME/deps
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH="$SIDEKICK_HOME/deps/depot_tools:$PATH"
update_depot_tools
mkdir chromium
cd chromium
fetch --nohooks --no-history chromium
```

Checkout a specific tag and sync local diffs. (10 min)
```
cd $SIDEKICK_HOME/deps/chromium/src
git fetch https://chromium.googlesource.com/chromium/src.git +refs/tags/131.0.6728.1:chromium_131.0.6728.1 --depth 1
git checkout tags/131.0.6728.1
gclient sync -D
gclient sync --with_branch_heads
gclient runhooks
rsync -av $SIDEKICK_HOME/deps/chromium_diff/ $SIDEKICK_HOME/deps/chromium/
```

Install Chromium dependencies. (10 min)
```
cd $SIDEKICK_HOME/deps/chromium/src
./build/install-build-deps.sh
```

Build Chromium. (10 min)
```
cd $SIDEKICK_HOME/deps/chromium/src
gn gen out/Default
ninja -C out/Default quic_server quic_client
```

### Generate certificates

See the section on generating certificates under "TCP Benchmarks".

## QUIC Benchmarks (Cloudflare)

### Install Rust (if needed)

Install the Rust toolchain (instructions [here](https://www.rust-lang.org/tools/install)):

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
```

### Build and Install Cloudflare QUIC (quiche)

This is a fork of quiche at a new (as of January 2025) tagged release (0.22.0). The quiche library is unchanged, but the sample quiche-server has been modified to expect a URI from the client of the form "/N", where N is the number of bytes it will generate and return.

```
cd $SIDEKICK_HOME/deps
git clone --recursive https://github.com/thearossman/quiche.git
./build_deps.sh 3
```

Building the repository may take a few minutes.

### Generate certificates

See the section on generating certificates under "TCP Benchmarks".

## QUIC Benchmarks (PicoQUIC)

### Build and Install PicoQUIC

This is a fork of picoquic on the main branch as of January 2024. The picoquic
library is unchanged, but the sample server has been modified to always return
N bytes, regardless of the client request, where N is an argument provided by
the CLI. There will also be some ongoing sidekick modifications...

```
cd $SIDEKICK_HOME/deps
git clone --recursive https://github.com/ygina/picoquic.git
./build_deps.sh 4
```

Building the repository may take a few minutes.

### Generate certificates

See the section on generating certificates under "TCP Benchmarks".
