"""
Provides a very minimal Mininet wrapper for testing the code in `proxy` without the
rest of the emulation framework. Single subnet. No TE.
"""

from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI

import argparse

# Configure bridging on r2
def start_bridge(p1):
    p1.cmd('sudo ip link set p1-eth0 promisc on')
    p1.cmd('sudo ip link set p1-eth1 promisc on')
    p1.cmd('sudo ip link add name br0 type bridge')
    p1.cmd('sudo ip link set p1-eth0 master br0 && sudo ip link set p1-eth1 master br0')
    p1.cmd('sudo ip link set dev br0 learning off') # not needed?
    p1.cmd('sudo ip link set br0 up')

def start_pcap(hosts, p1):
    outdir = '/tmp/proxy_pcaps'
    os.mkdir(outdir)
    for host in hosts:
        hosts[host].cmd(f'tcpdump -i {host}-eth0 inbound -w {outdir}/{host}-eth0-in.pcap -v &')
        hosts[host].cmd(f'tcpdump -i {host}-eth0 outbound -w {outdir}/{host}-eth0-out.pcap -v &')

    p1.cmd(f'tcpdump -i p1-eth0 inbound -w {outdir}/p1-eth0-in.pcap -v &')
    p1.cmd(f'tcpdump -i p1-eth1 inbound -w {outdir}/p1-eth1-in.pcap -v &')
    p1.cmd(f'tcpdump -i p1-eth0 outbound -w {outdir}/p1-eth0-out.pcap -v &')
    p1.cmd(f'tcpdump -i p1-eth1 outbound -w {outdir}/p1-eth1-out.pcap -v &')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='Basic',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--bridge', action='store_true',
                        help='Run bridging baseline (vs. proxy)')
    parser.add_argument('--pcap', action='store_true',
                        help='Take pcaps on all interfaces')
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

    # Start proxy or bridge
    if args.bridge:
        start_bridge(p1)
    else:
        output = p1.cmd('RUST_LOG=trace ./proxy/target/debug/bridge -i p1-eth0 -o p1-eth1 &')

    # Start pcaps
    if args.pcap:
        start_pcap({'h1': h1, 'h2': h2}, p1)

    # Run CLI for testing
    CLI(net)
    net.stop()

