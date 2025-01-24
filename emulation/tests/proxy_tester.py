"""
Provides a very minimal Mininet wrapper for testing the code in `proxy` without the
rest of the emulation framework. Single subnet. No TE.
"""

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI

import time
import argparse
import subprocess
import os

# Configure bridging on r2
def start_bridge(p1):
    p1.cmd('sudo ip link set p1-eth0 promisc on')
    p1.cmd('sudo ip link set p1-eth1 promisc on')
    p1.cmd('sudo ip link add name br0 type bridge')
    p1.cmd('sudo ip link set p1-eth0 master br0 && sudo ip link set p1-eth1 master br0')
    p1.cmd('sudo ip link set br0 up')

outdir = '/tmp/proxy_pcaps'
def start_pcap(hosts, p1, bridge):
    suffix = 'bridge' if bridge else 'proxy'
    print(f'Saving pcaps ({suffix}) to {outdir}')
    if not os.path.exists(outdir):
        os.mkdir(outdir)
    for host in hosts:
        hosts[host].cmd(f'tcpdump -i {host}-eth0 inbound -w {outdir}/{host}-eth0-in-{suffix}.pcap -v &')
        hosts[host].cmd(f'tcpdump -i {host}-eth0 outbound -w {outdir}/{host}-eth0-out-{suffix}.pcap -v &')

    p1.cmd(f'tcpdump -i p1-eth0 inbound -w {outdir}/p1-eth0-in-{suffix}.pcap -v &')
    p1.cmd(f'tcpdump -i p1-eth1 inbound -w {outdir}/p1-eth1-in-{suffix}.pcap -v &')
    p1.cmd(f'tcpdump -i p1-eth0 outbound -w {outdir}/p1-eth0-out-{suffix}.pcap -v &')
    p1.cmd(f'tcpdump -i p1-eth1 outbound -w {outdir}/p1-eth1-out-{suffix}.pcap -v &')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='Basic',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--bridge', action='store_true',
                        help='Run bridging baseline (vs. proxy)')
    parser.add_argument('--pcap', action='store_true',
                        help='Take pcaps on all interfaces')
    parser.add_argument('--cli', action='store_true',
                        help='Open CLI (rather than iperf)')
    parser.add_argument('--ping', action='store_true',
                        help='Run ping (rather than iperf)')
    args = parser.parse_args()

    # Create network: h1 -> p1 -> h2
    net = Mininet(controller=None, link=TCLink)
    h1 = net.addHost('h1', ip='10.0.2.9/24', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.2.10/24', mac='00:00:00:00:00:02')
    p1 = net.addHost('p1', ip='10.0.2.11/24', mac='00:00:00:00:00:03')
    net.addLink(h1, p1)
    net.addLink(p1, h2)
    net.build()

    # Disable annoying IPv6 features
    p1.cmd("sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    h1.cmd("sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    h2.cmd("sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1")

    # Disable checksum offload
    p1.cmd("ethtool -K p1-eth0 tx off rx off")
    p1.cmd("ethtool -K p1-eth1 tx off rx off")
    h1.cmd("ethtool -K h1-eth0 tx off rx off")
    h2.cmd("ethtool -K h2-eth0 tx off rx off")

    # Start proxy or bridge
    if args.bridge:
        start_bridge(p1)
    else:
        output = p1.cmd('RUST_LOG=error ./proxy/target/debug/bridge -i p1-eth0 -o p1-eth1 &')

    # Start pcaps
    if args.pcap:
        start_pcap({'h1': h1, 'h2': h2}, p1, args.bridge)

    if args.ping:
        print("Running ping")
        outp = h1.cmd(f'ping {h2.IP()} -c 10 -i 0.5')
        print(outp)

    if args.cli:
        CLI(net)
    elif not args.ping:
        h2_cmd = 'iperf3 -s -p 5201 &'
        print(h2_cmd)
        h2.cmd(h2_cmd)
        time.sleep(1) # give server time to start
        h1_cmd = f'iperf3 -c {h2.IP()} -p 5201 -t 2'
        print(h1_cmd)
        output = h1.cmd(h1_cmd)
        print('iperf3 output: ' + output)

    h2.cmd('killall iperf3')
    net.stop()

    if args.pcap:
        suffix = 'bridge' if args.bridge else 'proxy'
        print('fist 10 packets captured on h2-inbound:')
        res = subprocess.run(['tcpdump', '-r', f'{outdir}/h2-eth0-in-{suffix}.pcap', '-c', '10'],
                             capture_output=True, text=True)
        print(res.stdout)
        print('first 10 packets captured on h2-outbound:')
        res = subprocess.run(['tcpdump', '-r', f'{outdir}/h2-eth0-out-{suffix}.pcap', '-c', '10'],
                             capture_output=True, text=True)
        print(res.stdout)

