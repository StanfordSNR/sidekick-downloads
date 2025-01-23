import subprocess
import sys
import threading

from common import *
from mininet.net import Mininet
from mininet.link import TCLink

"""
Defines a basic network in Mininet with two hosts, h1 and h2.
"""
class EmulatedNetwork:
    METRICS = ['tx_packets', 'tx_bytes', 'rx_packets', 'rx_bytes']

    def __init__(self):
        self.net = Mininet(controller=None, link=TCLink)
        self.iface_to_host = {}

        # Keep track of background processes for cleanup
        self.background_processes = []

    @staticmethod
    def _mac(digit):
        assert 0 <= digit < 10
        return f'00:00:00:00:00:0{int(digit)}'

    @staticmethod
    def _ip(digit):
        assert 0 <= digit < 10
        return f'172.16.{int(digit)}.10/24'

    @staticmethod
    def _calculate_bdp(delay1, delay2, bw1, bw2):
        rtt_ms = 2 * (delay1 + delay2)
        bw_mbps = min(bw1, bw2)
        return rtt_ms * bw_mbps * 1000000. / 1000. / 8.

    def _config_iface(self, iface, netem: bool, pacing: bool=False,
                      delay=None, loss=None, bw=None, bdp=None, qdisc=None,
                      gso=True, tso=True, jitter=None):
        """Configures the given interface <iface>:
        - Netem: whether this is a network emulation node (i.e., delay, loss, etc.
          should be configured)
        - Loss: <loss>% stochastic packet loss
        - Delay: <delay>ms delay w/ ±<jitter>ms jitter, <delay_corr>% correlation
        - Base bandwidth: <bw> Mbit/s, range: <bw_min> to <bw_max> Mbit/s
        - Bandwidth-delay product: <bdp> is used to set the queue size
        """
        host = self.iface_to_host[iface]

        # Configure the end-host or proxy
        if not netem:
            # BBR requires fq (with pacing) for kernel versions <v4.20
            # https://groups.google.com/g/bbr-dev/c/zZ5c0qkWqbo/m/QulUwXLZAQAJ
            linux_version = get_linux_version()
            if pacing or linux_version < 5.0:
                self.popen(host, f'tc qdisc add dev {iface} root handle 2: '\
                                f'fq pacing', console_logger=DEBUG)
            return

        # Configure the network emulator node

        # Add netem with delay variability
        cmd = f'tc qdisc add dev {iface} root handle 2: '\
              f'netem delay {delay}ms '
        if loss is not None and int(loss) > 0:
            cmd += f'loss {loss}% '
        if jitter is not None:
            cmd += f'{jitter}ms {DEFAULT_DELAY_CORR}% distribution paretonormal'
        self.popen(host, cmd, console_logger=DEBUG)

        # Add HTB for bandwidth
        # Take the min because sch_htb complains about the quantum being too big
        # past 200,000 bytes. Otherwise calculate using the default r2q.
        # If using a policer at the proxy, make the bandwidth of the links
        # twice as high as the policed rate.
        r2q = 10
        quantum = min(int(bw*1000000/8 / r2q), 200000)
        self.popen(host, f'tc qdisc add dev {iface} parent 2: handle 3: ' \
                         f'htb default 10', console_logger=DEBUG)
        htb_rate = int(2*bw) if qdisc == 'policer' else bw
        self.popen(host, f'tc class add dev {iface} parent 3: ' \
                         f'classid 10 htb rate {htb_rate}Mbit quantum {quantum}',
                         console_logger=DEBUG)

        # Add queue management
        if qdisc == 'policer':
            # Burst time of 10ms
            burst = int(bw * 10 * 1000 / 8)
            queue_cmd = f'tc filter add dev {iface} parent 3: '\
                        f'protocol ip u32 match ip src 0.0.0.0/0 '\
                        f'action police rate {bw}mbit burst {burst} '\
                        f'conform-exceed drop'
            self.popen(host, queue_cmd, console_logger=DEBUG)
        elif qdisc is not None:
            queue_cmd = f'tc qdisc add dev {iface} parent 3:10 handle 11: '
            if qdisc == 'red':
                # The harddrop byte limit needs to be a min value or RED will
                # be unable to calculate the EWMA constant so that min >= avpkt
                limit = max(int(bdp*4), 1000*3*4*4)
                qmax = int(limit/4)
                qmin = int(qmax/3)
                avpkt = 1000
                # RED: WARNING. Burst (2*min+max)/(3*avpkt) seems to be too large.
                # RTNETLINK answers: Invalid argument
                burst = int(1 + qmin / avpkt)
                queue_cmd += f'red limit {limit} avpkt {avpkt} ' \
                             f'adaptive harddrop ' \
                             f'bandwidth {bw}Mbit burst {burst}'
            elif qdisc == 'bfifo-large':
                queue_cmd += f'bfifo limit {bdp}' # BDP
            elif qdisc == 'bfifo-small':
                limit = max(1500, int(0.1 * bdp)) # min(mtu, 0.1*BDP)
                queue_cmd += f'bfifo limit {limit}'
            elif qdisc == 'pie':
                # Memory limit, since packets are dropped based on target delay
                limit = int(4 * bdp / 1500)
                queue_cmd +=      f'pie limit {limit}'
            elif qdisc == 'codel':
                # Memory limit, since packets are dropped based on target delay
                limit = int(4 * bdp / 1500)
                queue_cmd += f'codel limit {limit} interval {rtt}ms'
            elif qdisc == 'fq_codel':
                queue_cmd += f'fq_codel'
            else:
                raise NotImplementedError(qdisc)
            self.popen(host, queue_cmd, console_logger=DEBUG)

        # Turn off tso and gso to send MTU-sized packets
        gso = 'on' if gso else 'off'
        tso = 'on' if tso else 'off'
        self.popen(host, f'ethtool -K {iface} gso {gso} tso {tso}',
                   console_logger=DEBUG)

    def set_tcp_congestion_control(self, cca):
        version = get_linux_version()
        cmd = f'sysctl -w net.ipv4.tcp_congestion_control={cca}'
        if version == 4.9 or version < 4.15:
            # Setting CCA on Mininet nodes will fail for kernel v4.9-4.14, but they
            # will inherit the CCA setting of the host.
            self.popen(None, cmd, stderr=True, console_logger=DEBUG)
        else:
            for host in self.net.hosts:
                self.popen(host, cmd, stderr=False, console_logger=DEBUG)

    def reset_statistics(self):
        """After a reset, an immediate snapshot would return all 0 values.
        """
        self.raw_metrics = self._read_raw_metrics()

    def snapshot_statistics(self):
        """Return a snapshot of metrics since the last reset. This is a
        difference from the statistics on reset.
        """
        now = self._read_raw_metrics()
        snapshot = {'ifaces': list(sorted(self.iface_to_host.keys()))}
        for metric in self.METRICS:
            snapshot[metric] = []
            for iface in snapshot['ifaces']:
                statistic = now[iface][metric] - self.raw_metrics[iface][metric]
                snapshot[metric].append(statistic)
        return snapshot

    def _read_raw_metrics(self):
        """Read the current raw metrics.
        """
        stats = {}
        for iface in self.iface_to_host:
            stats[iface] = {}
            for metric in self.METRICS:
                stats[iface][metric] = self._read_raw_metric(iface, metric)
        return stats

    def _read_raw_metric(self, iface, metric):
        """Read a single raw metric.
        """
        value = []
        def append_value(line):
            value.append(int(line.strip()))
        cmd = f'cat /sys/class/net/{iface}/statistics/{metric}'
        host = self.iface_to_host[iface]
        self.popen(host, cmd, func=append_value)
        if len(value) == 0:
            ERROR(f'failed to get metric {iface} {metric}')
            return 0
        else:
            return value[0]

    def popen(self, host, cmd, background=False, func=None, timeout=None,
              stdout=False, stderr=True, console_logger=TRACE, logfile=None,
              exit_on_err=True):
        """
        Start a process that executes a command on the given mininet host.
        Parameters:
        - host: the mininet host
        - cmd: a command string
        - background: whether to run as a background process
        - func: a function to execute on every line of output.
          the function takes as input (line,).
        - timeout: timeout, in seconds, to use on a mininet host
        - stdout: whether to log stdout to the console
        - stderr: whether to log stderr to the console
        - console_logger: log level function for logging to the console
        - logfile: the logfile to append output (both stdout and stderr) to

        Returns:
        - If a background process, returns the background process.
        - If not, returns True if there was a timeout and False if the process
          executed successfully.
        - For any other exitcodes, exits the program.
        """
        # Log the command to be executed
        host_str = '' if host is None else f'{host.name} '
        background_str = ' &' if background else ''
        console_logger(f'{host_str}{cmd}{background_str}')

        # Execute the command on the local host
        if host is None:
            assert not background
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            if p.stdout and stdout:
                print(p.stdout.strip(), file=sys.stderr)
            if p.stderr and stderr:
                print(p.stderr.strip(), file=sys.stderr)
            if p.returncode != 0:
                print(f'{cmd} = {p.returncode}', file=sys.stderr)
                if exit_on_err:
                    exit(1)
            return

        # Execute the command on a mininet host in the background
        if background:
            p = host.popen(cmd.split(), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
            self.background_processes.append(p)
            thread = threading.Thread(
                target=handle_background_process,
                args=(p, logfile, func),
            )
            thread.start()
            return p

        # Execute the command synchronously with a timeout
        cmd_input = cmd.split()
        if timeout is not None:
            cmd_input = ['timeout', f'{timeout}s'] + cmd_input
        p = host.popen(cmd_input, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
        for line, stream in read_subprocess_pipe(p):
            if stream == p.stdout and stdout:
                print(line, end='', file=sys.stderr)
            if stream == p.stderr and stderr:
                print(line, end='', file=sys.stderr)
            if logfile is not None:
                with open(logfile, 'a') as f:
                    f.write(line)
            if func is not None:
                func(line)

        # Handle the exitcode
        exitcode = p.wait()
        if exitcode == 0:
            return False
        elif exitcode == LINUX_TIMEOUT_EXITCODE:
            return True
        else:
            print(f'{host}({cmd}) = {exitcode}', file=sys.stderr)
            if exit_on_err:
                exit(1)

    def stop(self):
        for p in self.background_processes:
            p.terminate()
            p.wait()
        if self.net is not None:
            self.net.stop()

    def start_tcp_pep(self, logfile):
        self.popen(self.p1, 'ip rule add fwmark 1 lookup 100')
        self.popen(self.p1, 'ip route add local 0.0.0.0/0 dev lo table 100')
        self.popen(self.p1, 'iptables -t mangle -F')
        self.popen(self.p1, 'iptables -t mangle -A PREROUTING -i p1-eth1 -p tcp -j TPROXY --on-port 5000 --tproxy-mark 1')
        self.popen(self.p1, 'iptables -t mangle -A PREROUTING -i p1-eth0 -p tcp -j TPROXY --on-port 5000 --tproxy-mark 1')

        condition = threading.Condition()
        def notify_when_ready(line):
            if 'Pepsal started' in line:
                with condition:
                    condition.notify()

        # The start_tcp_pep() function blocks until the TCP PEP is ready to
        # split connections. That is, when we observe the 'Pepsal started'
        # string in the proxy output.
        self.popen(self.p1, 'pepsal -v', background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=SETUP_TIMEOUT)
            if not notified:
                raise TimeoutError(f'start_tcp_pep timeout {SETUP_TIMEOUT}s')


"""
Defines an emulated network in mininet with one intermediate hop between the
client and the server. The 1st link is between the client / data receiver (h1)
and the proxy (p1), and the 2nd link is between the proxy (p1) and the
server / data sender (h2).
Each link has a node (e1, e2) that emulates link properties (e.g., delay, loss,
bandwidth, jitter). Pacing is configured on each host interface.
e2 also handles L3 routing from h1 to h2.
"""
class OneHopNetwork(EmulatedNetwork):
    def __init__(self, delay1, delay2, loss1, loss2, bw1, bw2, jitter1, jitter2,
                 qdisc, pacing):
        super().__init__()

        # Add hosts, switches, and network emulation nodes
        self.h1 = self.net.addHost('h1', ip=self._ip(1),
                                   mac=self._mac(1))
        self.h2 = self.net.addHost('h2', ip=self._ip(2),
                                   mac=self._mac(2))
        self.e1 = self.net.addHost('e1')
        self.e2 = self.net.addHost('e2')
        self.p1 = self.net.addHost('p1', ip={self._ip(1).replace('10', '11')},
                                   mac=self._mac(3))

        # Add links
        self.net.addLink(self.h1, self.e1)
        self.net.addLink(self.e1, self.p1)
        self.net.addLink(self.p1, self.e2)
        self.net.addLink(self.e2, self.h2)
        self.net.build()

        # Initialize statistics
        self.iface_to_host = {
            'h1-eth0': self.h1,
            'p1-eth0': self.p1,
            'p1-eth1': self.p1,
            'h2-eth0': self.h2,
            'e1-eth0': self.e1,
            'e1-eth1': self.e1,
            'e2-eth0': self.e2,
            'e2-eth1': self.e2,
        }

        # Setup routing and forwarding (e2 acts as router)
        self.popen(self.e2, "ifconfig e2-eth0 0")
        self.popen(self.e2, "ifconfig e2-eth1 0")
        self.popen(self.e2, "ifconfig e2-eth0 hw ether 00:00:00:00:01:01")
        self.popen(self.e2, "ifconfig e2-eth1 hw ether 00:00:00:00:01:02")
        self.popen(self.e2, "ip addr add 172.16.1.1/24 brd + dev e2-eth0")
        self.popen(self.e2, "ip addr add 172.16.2.1/24 brd + dev e2-eth1")
        self.e2.cmd("echo 1 > /proc/sys/net/ipv4/ip_forward")
        self.popen(self.h1, "ip route add 172.16.2.0/24 via 172.16.1.1")
        self.popen(self.h2, "ip route add 172.16.1.0/24 via 172.16.2.1")

        # Set up transparent bridging on p1 and e1
        # \note if p1 is running a proxy that *also* bridges, then the kernel
        # bridge will be removed. `pepsal` does not bridge packets on its own.
        self.popen(self.p1, "brctl addbr br0")
        self.popen(self.p1, "brctl addif br0 p1-eth0")
        self.popen(self.p1, "brctl addif br0 p1-eth1")
        self.popen(self.p1, "ip link set dev br0 up")
        # IP needs to be assigned to bridge; put on same subnet as h1
        self.p1.cmd(f'sudo ip addr add {self.p1.IP().pop()} dev br0')
        # Don't forward packets destined for the proxy
        self.p1.cmd(f'sudo ebtables -A FORWARD -d {self.p1.MAC()} -j DROP')

        self.popen(self.e1, "brctl addbr br0")
        self.popen(self.e1, "brctl addif br0 e1-eth0")
        self.popen(self.e1, "brctl addif br0 e1-eth1")
        self.popen(self.e1, "ip link set dev br0 up")

        # Configure link latency, delay, bandwidth, and queue size
        # https://unix.stackexchange.com/questions/100785/bucket-size-in-tbf
        rtt = 2 * (delay1 + delay2)
        bdp = self._calculate_bdp(delay1, delay2, bw1, bw2)
        self._config_iface('h1-eth0', False, pacing)
        self._config_iface('p1-eth0', False, pacing)
        self._config_iface('p1-eth1', False, pacing)
        self._config_iface('h2-eth0', False, pacing)
        self._config_iface('e1-eth0', True, False, delay1, loss1, bw1, bdp, qdisc, jitter=jitter1)
        self._config_iface('e1-eth1', True, False, delay1, loss1, bw1, bdp, qdisc, jitter=jitter1)
        self._config_iface('e2-eth0', True, False, delay2, loss2, bw2, bdp, qdisc, jitter=jitter2)
        self._config_iface('e2-eth1', True, False, delay2, loss2, bw2, bdp, qdisc, jitter=jitter2)


"""
Defines an emulated network in mininet that directly connects the client /
data receiver (h1) to the server / data sender (h2) with a single link.
The link has a node (e1) that emulates link properties (e.g., delay, loss,
bandwidth, jitter). Pacing is configured on each host interface.
"""
class DirectNetwork(EmulatedNetwork):
    def __init__(self, delay, loss, bw, jitter, qdisc, pacing):
        super().__init__()

        # Add hosts and switches
        self.h1 = self.net.addHost('h1', ip=self._ip(1),
                                   mac=self._mac(1))
        self.h2 = self.net.addHost('h2', ip=self._ip(2),
                                   mac=self._mac(2))
        self.e1 = self.net.addHost('e1')

        # Add link
        self.net.addLink(self.h1, self.e1)
        self.net.addLink(self.e1, self.h2)
        self.net.build()

        # Initialize statistics
        self.iface_to_host = {
            'h1-eth0': self.h1,
            'h2-eth0': self.h2,
            'e1-eth0': self.e1,
            'e1-eth1': self.e1,
        }

        # Setup routing
        self.popen(self.h1, "ip route add 172.16.2.0/24 via 172.16.1.10")
        self.popen(self.h2, "ip route add 172.16.1.0/24 via 172.16.2.10")
        # Bridging on the network emulation nodes
        self.popen(self.e1, "brctl addbr br0")
        self.popen(self.e1, "brctl addif br0 e1-eth0")
        self.popen(self.e1, "brctl addif br0 e1-eth1")
        self.popen(self.e1, "ip link set dev br0 up")

        # Configure link latency, delay, bandwidth, and queue size
        # https://unix.stackexchange.com/questions/100785/bucket-size-in-tbf
        bdp = self._calculate_bdp(delay, 0, bw, bw)
        rtt = 2 * delay
        self._config_iface('h1-eth0', False, pacing)
        self._config_iface('h2-eth0', False, pacing)
        self._config_iface('e1-eth0', True, False, delay, loss, bw, bdp, qdisc, jitter=jitter)
        self._config_iface('e1-eth1', True, False, delay, loss, bw, bdp, qdisc, jitter=jitter)
