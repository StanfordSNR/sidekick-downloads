#!/bin/bash
set -e

print_usage() {
	echo "Usage: $0 on [binary]?"
	echo "Usage: $0 off"
	exit 1
}

# Check valid arguments
if [[ "$1" == "on" ]]; then
	if [[ $# -lt 1 || $# -gt 2 ]]; then
		print_usage
	fi
elif [[ "$1" == "off" ]]; then
	if [[ $# -ne 1 ]]; then
		print_usage
	fi
else
	print_usage
fi

# Turn the proxy on or off
if [ $1 == "on" ]; then
	# Assign a static IP to each interface
	ifconfig eth0 0
	ifconfig eth1 0
	ip addr add 10.1.10.3 dev eth0
	ip addr add 10.1.10.4 dev eth1
	ip link set dev eth0 mtu 1500
	ip link set dev eth1 mtu 1500
	#ip route add default via 10.1.10.1 dev eth0
	ip link set dev eth0 up
	ip link set dev eth1 up

	if [[ $# -eq 1 ]]; then
		exit 0
	elif [[ "$2" == "bridge" ]]; then
		./bin/$2 --client-interface eth1 --server-interface eth0
	else
		./bin/$2
	fi
elif [ $1 == "off" ]; then
	# Reset eth0 and eth1
	ip link set eth0 down
	ip link set eth1 down
	ip addr flush dev eth0
	ip addr flush dev eth1
	ip link set eth0 up
	ip link set eth1 up
fi
