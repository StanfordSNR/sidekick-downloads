
#!/bin/bash
help() {
	echo "USAGE: $0 [all|0|1]"
	echo "1 = pepsal"
	echo "2 = chromium"
	echo "3 = quiche"
	echo "4 = picoquic"
	echo "5 = sidekick"
	echo "6 = media"
	echo "7 = proxy-cycles-base"
	echo "8 = proxy-statistics"
	echo "9 = proxy-cycles-quack"
	exit 1
}

if [ $# -ne 1 ]; then
	help
fi

export SIDEKICK_HOME=$HOME/sidekick-downloads
export PATH="$SIDEKICK_HOME/deps/depot_tools:$PATH"

build_pepsal () {
cd $SIDEKICK_HOME/deps/pepsal
autoupdate
autoreconf --install
autoconf
./configure
make
sudo make install
}

build_quiche() {
cd $SIDEKICK_HOME/deps/quiche
git checkout v-0.22.0
cargo build --release --bin quiche-client
cargo build --release --bin quiche-server
}

build_chromium () {
cd $SIDEKICK_HOME/deps/chromium/src
gclient runhooks
gn gen out/Default
ninja -C out/Default quic_server quic_client
}

build_picoquic () {
	cd $SIDEKICK_HOME/deps/quack
	cargo build --release
	cd $SIDEKICK_HOME/sidekick_utils
	cargo build --release
	cd $SIDEKICK_HOME/quacker
	cargo build --release
	cd $SIDEKICK_HOME/deps/picoquic
	cmake -DPICOQUIC_FETCH_PTLS=Y .
	cmake --build . -t picoquic_sample
}

build_sidekick() {
	cd $SIDEKICK_HOME/proxy
	cargo build --release --bin bridge
	cargo build --release --bin sidekick
	cargo build --release --bin sidekick_multicast
	cd $SIDEKICK_HOME/rtunnel
	cargo build --release --bin rtunnel
	cd $SIDEKICK_HOME/quacker
	cargo build --release --bin quacker
}

build_media() {
	cd $SIDEKICK_HOME/media
	cargo build --release --bin endpoint
	cargo build --release --bin multicast_server
	cargo build --release --bin multicast_client
}

build_proxy_cycles_base() {
	cd $SIDEKICK_HOME/proxy
	cargo build --release --bin sidekick --features cycles_base
}

build_proxy_statistics() {
	cd $SIDEKICK_HOME/proxy
	cargo build --release --bin sidekick --features cache_statistics
	cargo build --release --bin sidekick_multicast --features cache_statistics
}

build_proxy_cycles_quack() {
	cd $SIDEKICK_HOME/proxy
	cargo build --release --bin sidekick --features cycles_quack
}

if [ $1 == "all" ]; then
	build_pepsal
	build_chromium
	build_quiche
	build_picoquic
	build_sidekick
	build_media
elif [ $1 -eq 1 ]; then
	build_pepsal
elif [ $1 -eq 2 ]; then
	build_chromium
elif [ $1 -eq 3 ]; then
	build_quiche
elif [ $1 -eq 4 ]; then
	build_picoquic
elif [ $1 -eq 5 ]; then
	build_sidekick
elif [ $1 -eq 6 ]; then
	build_media
elif [ $1 -eq 7 ]; then
	build_proxy_cycles_base
elif [ $1 -eq 8 ]; then
	build_proxy_statistics
elif [ $1 -eq 9 ]; then
	build_proxy_cycles_quack
else
	help
fi
