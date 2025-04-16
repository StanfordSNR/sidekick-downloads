#!/bin/bash
set -e

if [ "$#" -ne 1 ]; then
	echo "Usage: $0 [on|off]"
	exit 1
fi

if [ $1 == "on" ]; then
	# Start the bridge
	brctl addbr br0
	brctl addif br0 eth0
	brctl addif br0 eth1
	ip link set dev br0 address 10:00:00:00:00:00
	ip link set dev br0 up

	# Configure other interfaces
	ifconfig eth0 0
	ifconfig eth1 0
	ebtables -A FORWARD -d 10:00:00:00:00:00 -j DROP
elif [ $1 == "off" ]; then
	# Tear down the bridge
	ip link set br0 down
	brctl delif br0 eth0
	brctl delif br0 eth1
	brctl delbr br0

	# Reset eth0 and eth1
	ip addr flush dev eth0
	ip addr flush dev eth1
	ip link set eth0 up
	ip link set eth1 up
	dhclient eth0
	ebtables -F
else
	echo "Usage: $0 [on|off]"
	exit 1
fi
