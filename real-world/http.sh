#!/bin/bash
set -e

print_usage() {
	echo "Usage: $0 server [nbytes]"
	echo "Usage: $0 client-baseline [nbytes] [server_ip]"
	echo "Usage: $0 client-sidekick [nbytes] [server_ip]"
	exit 1
}

# Check valid arguments
if [[ $# -lt 2 ]]; then
	print_usage
fi

# Start the media endpoint
SIDEKICK_HOME=$HOME/sidekick-downloads
SERVER_PORT=4433
CERTFILE=$SIDEKICK_HOME/deps/certs/out/leaf_cert.pem
PRIVATE_KEYFILE=$SIDEKICK_HOME/deps/certs/out/leaf_cert.key
ACK_DELAY_MS=30  # a little more than 2x quACK rtt
QUACK_PROXY_ADDR=10.1.10.3:5252
QUACK_FREQ_MS=10
QUACK_FREQ_PKTS=16
QUACK_THRESHOLD=40
if [ $1 == "server" ]; then
	if [[ $# -ne 2 ]]; then
		print_usage
	fi
	$SIDEKICK_HOME/deps/picoquic/picoquic_sample server $SERVER_PORT $CERTFILE $PRIVATE_KEYFILE . $2 cubic
elif [ $1 == "client-baseline" ]; then
	if [[ $# -ne 3 ]]; then
		print_usage
	fi
	$SIDEKICK_HOME/deps/picoquic/picoquic_sample client $3 $SERVER_PORT /tmp cubic $(pwd)/http_client_baseline.log 0 $2.html
elif [ $1 == "client-sidekick" ]; then
	if [[ $# -ne 3 ]]; then
		print_usage
	fi
	$SIDEKICK_HOME/deps/picoquic/picoquic_sample client $3 $SERVER_PORT /tmp cubic $(pwd)/http_client_sidekick.log \
		$ACK_DELAY_MS $QUACK_THRESHOLD $QUACK_FREQ_PKTS $QUACK_FREQ_MS $QUACK_PROXY_ADDR 0 1 1 $2.html
else
	print_usage
fi
