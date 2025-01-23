import unittest
from network import *


class PingResult:
    def __init__(self, output):
        pattern = (
            r'\s+(?P<packets_tx>\d+) packets transmitted, '
            r'(?P<packets_rx>\d+) received, '
            r'(?P<packet_loss>[\d.]+)% packet loss, '
            r'time (?P<total_time>\d+)ms\s+'
            r'rtt min/avg/max/mdev = '
            r'(?P<rtt_min>[\d.]+)/(?P<rtt_avg>[\d.]+)/'
            r'(?P<rtt_max>[\d.]+)/(?P<rtt_mdev>[\d.]+) ms.*'
        )
        match = re.search(pattern, output)
        if match:
            self.success = True
            self.match = match.groupdict()
        else:
            self.success = False

    def packets_tx(self):
        return int(self.match['packets_tx'])

    def packets_rx(self):
        return int(self.match['packets_rx'])

    def packet_loss(self):
        """Packet loss, in %"""
        return float(self.match['packet_loss'])

    def total_time(self):
        """Total time, in ms"""
        return float(self.match['total_time'])

    def rtt_min(self):
        """Minimum RTT, in ms"""
        return float(self.match['rtt_min'])

    def rtt_avg(self):
        """Average RTT, in ms"""
        return float(self.match['rtt_avg'])

    def rtt_max(self):
        """Maximum RTT, in ms"""
        return float(self.match['rtt_max'])

    def rtt_mdev(self):
        """Mean deviation, in ms"""
        return float(self.match['rtt_mdev'])


class NetworkTestCase(unittest.TestCase):
    def setUp(self):
        # Suppress stderr logging from network setup
        self._stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')

    def setUpOneHopNetwork(self, delay1=1, delay2=10, loss1=0, loss2=0,
                           bw1=50, bw2=10, jitter1=None, jitter2=None,
                           qdisc='red', pacing=False) -> OneHopNetwork:
        net = OneHopNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                            jitter1, jitter2, qdisc, pacing)
        return net

    def setUpDirectNetwork(self, delay=10, loss=0, bw=10, jitter=None,
                           qdisc='red', pacing=False) -> DirectNetwork:
        net = DirectNetwork(delay, loss, bw, jitter, qdisc, pacing)
        return net

    def ping(self, node1, node2, n=1) -> PingResult:
        """Send n pings from node1 from node2 at a 0.1s interval.

        Asserts that the node is reachable and at least one ping reply was
        received. Assertions may be flaky with loss, but n should be large
        enough that receiving no replies is statistically unlikely.

        Returns the parsed ping statistics.
        """
        output = node1.cmd(f'ping -i 0.1 -c {n} {node2.IP()}')
        result = PingResult(output)
        debug_output = f'{node1.name} -> {node2.name}\n{output}'
        self.assertTrue(result.success, debug_output)
        self.assertEqual(result.packets_tx(), n)
        return result


class TestNetStatistics(unittest.TestCase):
    def setUp(self):
        pass

    def test_tx_and_rx_statistics(self):
        pass


class TestEmulatedNetwork(unittest.TestCase):
    def test_ip(self):
        self.assertEqual(EmulatedNetwork._ip(1), '172.16.1.10/24')
        self.assertEqual(EmulatedNetwork._ip(2), '172.16.2.10/24')
        self.assertEqual(EmulatedNetwork._ip(0), '172.16.0.10/24')
        self.assertEqual(EmulatedNetwork._ip(9), '172.16.9.10/24')
        with self.assertRaises(AssertionError):
            EmulatedNetwork._ip(10)
        with self.assertRaises(AssertionError):
            EmulatedNetwork._ip(-1)

    def test_mac(self):
        self.assertEqual(EmulatedNetwork._mac(1), '00:00:00:00:00:01')
        self.assertEqual(EmulatedNetwork._mac(2), '00:00:00:00:00:02')
        self.assertEqual(EmulatedNetwork._mac(0), '00:00:00:00:00:00')
        self.assertEqual(EmulatedNetwork._mac(9), '00:00:00:00:00:09')
        with self.assertRaises(AssertionError):
            EmulatedNetwork._mac(10)
        with self.assertRaises(AssertionError):
            EmulatedNetwork._mac(-1)

    def test_calculate_bdp(self):
        delay1 = 20 # ms
        delay2 = 10
        bw1 = 10 # Mbit/s
        bw2 = 1000
        expected_mbits = 0.6 # 60ms * 10Mbit/s
        expected_bytes = expected_mbits * 1000000 / 8
        actual_bytes = EmulatedNetwork._calculate_bdp(delay1, delay2, bw1, bw2)
        self.assertEqual(actual_bytes, expected_bytes,
                         'calculated bdp in bytes')


class TestNetworkReachability(NetworkTestCase):
    def assertReachable(self, node1, node2, n=1):
        result = self.ping(node1, node2, n)
        debug_output = f'{node1.name} -> {node2.name}'
        self.assertGreater(result.packets_rx(), 0, debug_output)

    def test_one_hop_hosts_are_reachable(self):
        net = self.setUpOneHopNetwork()
        self.assertReachable(net.h1, net.h2)
        self.assertReachable(net.h2, net.h1)

    def test_one_hop_proxy_is_reachable(self):
        net = self.setUpOneHopNetwork()
        self.assertReachable(net.r1, net.h1)
        self.assertReachable(net.r1, net.h2)
        self.assertReachable(net.h1, net.r1)
        self.assertReachable(net.h2, net.r1)

    def test_direct_hosts_are_reachable(self):
        net = self.setUpDirectNetwork()
        self.assertReachable(net.h1, net.h2)
        self.assertReachable(net.h2, net.h1)


class TestDelayConfig(NetworkTestCase):
    def assertDelayIsCorrect(self, node1, node2, expected_delay, n=10):
        """RTTs are accurate to the nearest ms."""
        ping = self.ping(node1, node2, n)
        debug_output = f'{node1.name} -> {node2.name}'
        self.assertEqual(ping.packets_rx(), ping.packets_tx(),
            'same number of pings are sent as received with zero loss')
        expected_rtt = expected_delay * 2
        self.assertAlmostEqual(ping.rtt_min(), expected_rtt, 0, debug_output)
        self.assertAlmostEqual(ping.rtt_max(), expected_rtt, 0, debug_output)
        self.assertAlmostEqual(ping.rtt_avg(), expected_rtt, 0, debug_output)
        self.assertAlmostEqual(ping.rtt_mdev(), 0, 0, debug_output)

    def test_direct_delay_config(self):
        delay = 100  # one-way delay, in ms
        net = self.setUpDirectNetwork(delay=delay)

        # get the ARPs over with
        self.ping(net.h1, net.h2, 1)
        self.ping(net.h2, net.h1, 1)

        # ping each pair of nodes
        self.assertDelayIsCorrect(net.h1, net.h2, delay)
        self.assertDelayIsCorrect(net.h2, net.h1, delay)

    def test_one_hop_delay_config(self):
        delay1 = 100  # one-way delay, in ms
        delay2 = 2
        net = self.setUpOneHopNetwork(delay1=delay1, delay2=delay2)

        for (node1, node2, delay) in [
            (net.h1, net.h2, delay1 + delay2),
            (net.h1, net.r1, delay1),
            (net.r1, net.h2, delay2),
        ]:
            # get the ARPs over with
            self.ping(node1, node2, 1)
            self.ping(node2, node1, 1)
            # ping each pair of nodes
            self.assertDelayIsCorrect(node1, node2, delay)
            self.assertDelayIsCorrect(node2, node1, delay)
