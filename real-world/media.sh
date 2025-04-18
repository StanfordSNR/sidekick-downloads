#!/bin/bash
set -e

print_usage() {
	echo "Usage: $0 server [rtt_ms]"
	echo "Usage: $0 client-baseline [rtt_ms] [timeout_s] [server_ip]"
	echo "Usage: $0 client-sidekick [rtt_ms] [timeout_s] [server_ip]"
	exit 1
}

# Check valid arguments
if [[ $# -lt 2 ]]; then
	print_usage
fi

# Start the media endpoint
SIDEKICK_HOME=$HOME/sidekick-downloads
FREQUENCY_MS=20
NACK_DELAY_MS=45  # a little more than 2x the frequency
SERVER_PORT=5201
QUACK_PROXY_ADDR=10.1.10.3:5252
QUACK_THRESHOLD=8
if [ $1 == "server" ]; then
	if [[ $# -ne 2 ]]; then
		print_usage
	fi
	$SIDEKICK_HOME/media/target/release/endpoint --logfile $(pwd)/media_server.log \
		--nack-frequency $2 --frequency $FREQUENCY_MS --port $SERVER_PORT server
elif [ $1 == "client-baseline" ]; then
	if [[ $# -ne 4 ]]; then
		print_usage
	fi
	$SIDEKICK_HOME/media/target/release/endpoint --logfile $(pwd)/media_client_baseline.log \
		--nack-frequency $2 --frequency $FREQUENCY_MS \
		client --timeout $3 --addr $4:$SERVER_PORT
elif [ $1 == "client-sidekick" ]; then
	if [[ $# -ne 4 ]]; then
		print_usage
	fi
	$SIDEKICK_HOME/media/target/release/endpoint --logfile $(pwd)/media_client_sidekick.log \
		--nack-frequency $2 --frequency $FREQUENCY_MS \
		--nack-delay $NACK_DELAY_MS \
		--quacker --send-on-nack --threshold $QUACK_THRESHOLD --frequency-pkts 0 --frequency-ms 0 --hint --target-addr $QUACK_PROXY_ADDR \
		client --timeout $3 --addr $4:$SERVER_PORT
else
	print_usage
fi
