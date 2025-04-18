#!/bin/bash
set -e
if [ "$#" -ne 1 ]; then
	echo "Usage: $0 <binary_name>"
	exit 1
fi

scp sidekick:~/sidekick-downloads/proxy/target/aarch64-unknown-linux-gnu/release/$1 bin/
