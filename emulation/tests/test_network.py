"""
Test network.py.
"""
import unittest
import os
import time
import tempfile
from network import *


class PingResult:
    def __init__(self, output):
        # Parse each individual ping
        self.pings = []
        pattern = r'bytes from ([\d\.]+): icmp_seq=(\d+)'
        for line in output.split('\n'):
            match = re.search(pattern, line)
            if match:
                ip = match.group(1)
                icmp_seq = int(match.group(2))
                self.pings.append((ip, icmp_seq))

        # Parse the result summary
        pattern = (
            r'\s+(?P<packets_tx>\d+) packets transmitted, '
            r'(?P<packets_rx>\d+) received, .*'
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

        # Default parameters
        self.threshold = 20
        self.quackee_port = 5252

        self.net = None
        self.stopped = True

    def stopNetwork(self):
        if not self.stopped:
            self.net.stop()
            self.stopped = True

    def tearDown(self):
        self.stopNetwork()

    def setUpOneHopNetwork(
        self, delay1=1, delay2=10, loss1=0, loss2=0, bw1=50, bw2=10,
        jitter1=None, jitter2=None, qdisc='red', pacing=False, setup_time=0,
        bridge_proxy=True, cache=True,
    ) -> OneHopNetwork:
        net = OneHopNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                            jitter1, jitter2, qdisc, pacing, bridge_proxy)
        if cache:
            self.stopNetwork()
            self.net = net
            self.stopped = False
        if setup_time > 0:
            time.sleep(setup_time)
        return net

    def setUpMulticastNetwork(
        self, num_clients, delay1=1, delay2=10, loss1=0, loss2=0, bw1=50,
        bw2=10, jitter1=None, jitter2=None, qdisc='red', pacing=False,
        setup_time=0, bridge_proxy=True, cache=True,
    ) -> MulticastNetwork:
        net = MulticastNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                               qdisc, pacing, num_clients, bridge_proxy)
        if cache:
            self.stopNetwork()
            self.net = net
            self.stopped = False
        if setup_time > 0:
            time.sleep(setup_time)
        return net

    def setUpDirectNetwork(
        self, delay=10, loss=0, bw=10, jitter=None, qdisc='red', pacing=False,
        setup_time=0, cache=True,
    ) -> DirectNetwork:
        net = DirectNetwork(delay, loss, bw, jitter, qdisc, pacing)
        if cache:
            self.stopNetwork()
            self.net = net
            self.stopped = False
        if setup_time > 0:
            time.sleep(setup_time)
        return net

    def ping(self, node1, node2, n=1, interval=0.05) -> PingResult:
        """Send n pings from node1 from node2.

        Asserts that the node is reachable and at least one ping reply was
        received. Assertions may be flaky with loss, but n should be large
        enough that receiving no replies is statistically unlikely.

        Returns the parsed ping statistics.
        """
        output = node1.cmd(f'ping -i {interval} -c {n} {node2.IP()}')
        result = PingResult(output)
        debug_output = f'{node1.name} -> {node2.name}\n{output}'
        self.assertTrue(result.success, debug_output)
        self.assertEqual(result.packets_tx(), n)
        return result


class TestMulticastNetwork(NetworkTestCase):
    def _test_multicast_reachability(self, num_clients, num_pings=2):
        net = self.setUpMulticastNetwork(num_clients)
        self.assertEqual(net.server.name, 'h0')
        self.assertEqual(len(net.clients), num_clients)
        for i in range(num_clients):
            self.assertEqual(net.clients[i].name, f'h{i+1}')
        output = net.server.cmd(f'ping -t 2 -c {num_pings} 239.0.0.1')
        result = PingResult(output)
        self.assertTrue(result.success)
        self.assertEqual(result.packets_tx(), num_pings)
        ping_ips = set([ip for (ip, _) in result.pings])
        self.assertEqual(len(ping_ips), num_clients, ping_ips)

    def test_multicast_reachability_one_client(self):
        self._test_multicast_reachability(1)

    def test_multicast_reachability_multiple_clients(self):
        self._test_multicast_reachability(3)


class TestNetStatistics(NetworkTestCase):
    def assertSchemaIsCorrect(self, net, expected_ifaces):
        stats = net.snapshot_statistics()
        self.assertEqual(len(stats), 1 + len(EmulatedNetwork.METRICS), stats)
        self.assertIn('ifaces', stats)
        ifaces = stats['ifaces']
        self.assertEqual(len(ifaces), len(expected_ifaces))
        self.assertEqual(ifaces, list(sorted(expected_ifaces)))
        for metric in EmulatedNetwork.METRICS:
            self.assertIn(metric, stats)
            self.assertEqual(len(stats[metric]), len(ifaces))

    def test_statistics_schema(self):
        host_ifaces = ['h1-eth0', 'h2-eth0']
        proxy_ifaces = ['p1-eth0', 'p1-eth1']

        # one-hop network
        net = self.setUpOneHopNetwork()
        self.assertSchemaIsCorrect(net, host_ifaces + proxy_ifaces)

        # direct network
        net = self.setUpDirectNetwork()
        self.assertSchemaIsCorrect(net, host_ifaces)

        # one-hop network with a sidekick
        cwd = os.getcwd()
        os.chdir('..') # run from sidekick base directory
        net = self.setUpOneHopNetwork(bridge_proxy=False)
        net.start_sidekick(self.threshold, self.quackee_port, logfile=None)
        self.assertSchemaIsCorrect(net, host_ifaces + proxy_ifaces)
        os.chdir(cwd)

    def test_reset_statistics(self):
        net = self.setUpOneHopNetwork()
        self.ping(net.h1, net.h2, 100, interval=0.01)
        stats1 = net.snapshot_statistics()

        # check statistics have been reduced since there may be non-ping packets
        net.reset_statistics()
        stats2 = net.snapshot_statistics()
        for i, iface in enumerate(stats1['ifaces']):
            for metric in EmulatedNetwork.METRICS:
                debug_str = f'{iface} {metric}'
                self.assertLess(stats2[metric][i], stats1[metric][i], debug_str)

    def test_sending_packets_without_loss(self):
        net = self.setUpOneHopNetwork()

        # get the ARPs over with
        self.ping(net.h1, net.h2, 1)
        self.ping(net.h2, net.h1, 1)

        # send n pings from h1 to h2
        n = 100
        net.reset_statistics()
        self.ping(net.h1, net.h2, n, interval=0.01)

        # 14-byte Ethernet header
        # 20-byte IPv4 header
        # 8-byte ICMP header
        header_size = 42

        # all interfaces have sent and received at least n packets
        stats = net.snapshot_statistics()
        for i, iface in enumerate(stats['ifaces']):
            self.assertGreaterEqual(stats['tx_packets'][i], n, iface)
            self.assertGreaterEqual(stats['rx_packets'][i], n, iface)
            self.assertGreater(stats['tx_bytes'][i], n * header_size, iface)
            self.assertGreater(stats['rx_bytes'][i], n * header_size, iface)

    @unittest.skip('skip flaky test')
    def test_sending_packets_with_loss(self):
        net = self.setUpOneHopNetwork(loss1=20)

        # get the ARPs over with
        self.ping(net.h1, net.h2, 5)
        self.ping(net.h2, net.h1, 5)

        # send n pings from h1 to h2
        num_requests = 100
        net.reset_statistics()
        self.ping(net.h1, net.h2, num_requests, interval=0.01)

        # some packets are lost on the way there
        # ifaces = ['h1-eth0', 'h2-eth0', 'p1-eth0', 'p1-eth1']
        stats = net.snapshot_statistics()
        self.assertGreaterEqual(stats['tx_packets'][0], num_requests)
        self.assertLess(stats['rx_packets'][2], num_requests)
        self.assertLess(stats['tx_packets'][3], num_requests)
        self.assertLess(stats['rx_packets'][1], num_requests)

        # some packets are lost on the way back
        self.assertLess(stats['tx_packets'][1], num_requests)
        self.assertLess(stats['rx_packets'][3], num_requests)
        num_replies = stats['tx_packets'][2]
        self.assertLess(num_replies, num_requests)
        self.assertLess(stats['rx_packets'][0], num_replies)


class TestEmulatedNetwork(unittest.TestCase):
    def test_ip(self):
        self.assertEqual(EmulatedNetwork._ip(1, 10), '172.16.1.10/24')
        self.assertEqual(EmulatedNetwork._ip(2, 10), '172.16.2.10/24')
        self.assertEqual(EmulatedNetwork._ip(0, 10), '172.16.0.10/24')
        self.assertEqual(EmulatedNetwork._ip(9, 10), '172.16.9.10/24')
        self.assertEqual(EmulatedNetwork._ip(9, 21), '172.16.9.21/24')
        with self.assertRaises(AssertionError):
            EmulatedNetwork._ip(10, 10)
        with self.assertRaises(AssertionError):
            EmulatedNetwork._ip(-1, 10)

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

    def test_one_hop_hosts_are_reachable_pepsal(self):
        net = self.setUpOneHopNetwork()
        net.start_tcp_pep(logfile=None)
        self.assertReachable(net.h1, net.h2)
        self.assertReachable(net.h2, net.h1)

    def test_one_hop_hosts_are_reachable_sidekick(self):
        cwd = os.getcwd()
        os.chdir('..') # run from sidekick base directory
        net = self.setUpOneHopNetwork(bridge_proxy=False)
        net.start_sidekick(self.threshold, self.quackee_port, logfile=None)
        self.assertReachable(net.h1, net.h2)
        self.assertReachable(net.h2, net.h1)
        os.chdir(cwd)

    def test_one_hop_proxy_is_reachable(self):
        net = self.setUpOneHopNetwork()
        self.assertReachable(net.p1, net.h1)
        self.assertReachable(net.p1, net.h2)
        self.assertReachable(net.h1, net.p1)
        self.assertReachable(net.h2, net.p1)

    def test_one_hop_proxy_is_reachable_pepsal(self):
        net = self.setUpOneHopNetwork()
        net.start_tcp_pep(logfile=None)
        self.assertReachable(net.p1, net.h1)
        self.assertReachable(net.p1, net.h2)
        self.assertReachable(net.h1, net.p1)
        self.assertReachable(net.h2, net.p1)

    def test_one_hop_proxy_is_reachable_sidekick(self):
        cwd = os.getcwd()
        os.chdir('..')
        net = self.setUpOneHopNetwork(bridge_proxy=False)
        net.start_sidekick(self.threshold, self.quackee_port, logfile=None)
        self.assertReachable(net.p1, net.h1)
        self.assertReachable(net.p1, net.h2)
        self.assertReachable(net.h1, net.p1)
        self.assertReachable(net.h2, net.p1)
        os.chdir(cwd)

    def test_direct_hosts_are_reachable(self):
        net = self.setUpDirectNetwork()
        self.assertReachable(net.h1, net.h2)
        self.assertReachable(net.h2, net.h1)

    def test_multicast_hosts_are_reachable_one_client(self):
        net = self.setUpMulticastNetwork(1)
        self.assertReachable(net.server, net.clients[0])
        self.assertReachable(net.clients[0], net.server)

    def test_multicast_hosts_are_reachable_multiple_client(self):
        net = self.setUpMulticastNetwork(2)
        self.assertReachable(net.server, net.clients[0])
        self.assertReachable(net.server, net.clients[1])
        self.assertReachable(net.clients[0], net.server)
        self.assertReachable(net.clients[1], net.server)


class TestDelayConfig(NetworkTestCase):
    def assertDelayIsCorrect(self, node1, node2, expected_delay, n=10):
        """RTTs are accurate to the nearest ms."""
        ping = self.ping(node1, node2, n)
        debug_output = f'{node1.name} -> {node2.name}'
        self.assertEqual(ping.packets_rx(), ping.packets_tx(),
            'same number of pings are sent as received with zero loss')
        expected_rtt = expected_delay * 2
        delta = 0.2 * expected_rtt  # within 20% of the expected RTT
        self.assertAlmostEqual(ping.rtt_min(), expected_rtt,
            msg=debug_output, delta=delta)
        self.assertAlmostEqual(ping.rtt_max(), expected_rtt,
            msg=debug_output, delta=delta)
        self.assertAlmostEqual(ping.rtt_avg(), expected_rtt,
            msg=debug_output, delta=delta)
        self.assertAlmostEqual(ping.rtt_mdev(), 0,
            msg=debug_output, delta=delta)

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
            (net.h1, net.p1, delay1),
            (net.p1, net.h2, delay2),
        ]:
            # get the ARPs over with
            self.ping(node1, node2, 1)
            self.ping(node2, node1, 1)
            # ping each pair of nodes
            self.assertDelayIsCorrect(node1, node2, delay)
            self.assertDelayIsCorrect(node2, node1, delay)


class TestLossConfig(NetworkTestCase):
    def assertLossIsCorrect(self, node1, node2, loss: bool, n=30):
        ping = self.ping(node1, node2, n)
        debug_output = f'{node1.name} -> {node2.name}'
        if loss:
            self.assertLess(ping.packets_rx(), ping.packets_tx(), debug_output)
            self.assertGreater(ping.packet_loss(), 0, debug_output)
        else:
            self.assertEqual(ping.packets_rx(), ping.packets_tx(), debug_output)
            self.assertEqual(ping.packet_loss(), 0, debug_output)

    @unittest.skip('pings are flaky when there is loss')
    def test_direct_loss_config(self):
        net = self.setUpDirectNetwork(loss=20, setup_time=2)
        self.assertLossIsCorrect(net.h1, net.h2, True)
        self.assertLossIsCorrect(net.h2, net.h1, True)

    @unittest.skip('pings are flaky when there is loss')
    def test_one_hop_loss_config(self):
        net = self.setUpOneHopNetwork(loss1=20, loss2=20, setup_time=2)
        for (node1, node2) in [
            (net.h1, net.h2),
            (net.h1, net.p1),
            (net.p1, net.h2),
        ]:
            self.assertLossIsCorrect(node1, node2, True)
            self.assertLossIsCorrect(node2, node1, True)

    @unittest.skip('pings are flaky when there is loss')
    def test_one_hop_asymmetric_loss_config(self):
        net = self.setUpOneHopNetwork(loss1=20, loss2=0, setup_time=2)
        for (node1, node2, loss) in [
            (net.h1, net.h2, True),
            (net.h1, net.p1, True),
            (net.p1, net.h2, False),
        ]:
            self.assertLossIsCorrect(node1, node2, loss)
            self.assertLossIsCorrect(node2, node1, loss)


class TestBandwidthConfig(NetworkTestCase):
    pass


class TestQdiscConfig(NetworkTestCase):
    pass


class TestSetTCPCongestionControl(NetworkTestCase):
    def setUp(self):
        super().setUp()
        self.net1 = self.setUpDirectNetwork(cache=False)
        self.net2 = self.setUpOneHopNetwork(cache=False)

    def tearDown(self):
        self.net1.stop()
        self.net2.stop()

    def assertCCAEquals(self, node, expected_cca):
        output = node.cmd('sysctl net.ipv4.tcp_congestion_control')
        pattern = r' = (\w+)'
        match = re.search(pattern, output)
        self.assertFalse(match is None)
        self.assertEqual(match.group(1), expected_cca)

    def assertCCAsAllEqual(self, expected_cca):
        self.assertCCAEquals(self.net1.h1, expected_cca)
        self.assertCCAEquals(self.net1.h2, expected_cca)
        self.assertCCAEquals(self.net2.h1, expected_cca)
        self.assertCCAEquals(self.net2.h2, expected_cca)
        self.assertCCAEquals(self.net2.p1, expected_cca)

    def _test_can_set_cca(self, cca):
        self.net1.set_tcp_congestion_control(cca)
        self.net2.set_tcp_congestion_control(cca)
        self.assertCCAsAllEqual(cca)

    def test_default_is_cubic(self):
        self.assertCCAsAllEqual('cubic')

    def test_can_set_cubic(self):
        self._test_can_set_cca('cubic')

    def test_can_set_reno(self):
        self._test_can_set_cca('reno')

    def test_can_set_bbr(self):
        self._test_can_set_cca('bbr')


class TestPopen(NetworkTestCase):
    def setUp(self):
        super().setUp()
        self.setUpDirectNetwork()

    def test_invalid_configurations(self):
        logfile = tempfile.NamedTemporaryFile()
        cmd = 'true'
        with self.assertRaises(AssertionError):
            self.net.popen(None, cmd, func=lambda line: line)
        with self.assertRaises(AssertionError):
            self.net.popen(None, cmd, timeout=60)
        with self.assertRaises(AssertionError):
            self.net.popen(None, cmd, logfile=logfile.name)
        with self.assertRaises(AssertionError):
            self.net.popen(self.net.h1, cmd, background=True, timeout=60)

    def test_timeout_succeeds(self):
        """Test timeout, only on mininet hosts and synchronous processes.
        """
        host = self.net.h1
        self.assertFalse(self.net.popen(host, 'sleep 1', timeout=None))
        self.assertFalse(self.net.popen(host, 'sleep 1', timeout=2))
        self.assertTrue(self.net.popen(host, 'sleep 2', timeout=1))

    def _test_raises_exception_on_bad_exitcode(self, host):
        good_cmd = 'true'
        bad_cmd = '>'  # todo
        self.net.popen(host, good_cmd, raise_error=True)
        self.net.popen(host, good_cmd, raise_error=False) # no error to suppress
        with self.assertRaises(ValueError, msg='error raises an exception'):
            self.net.popen(host, bad_cmd, raise_error=True)
        self.net.popen(host, bad_cmd, raise_error=False)  # error is suppressed

    def test_raises_exception_on_bad_exitcode(self):
        self._test_raises_exception_on_bad_exitcode(None)
        self._test_raises_exception_on_bad_exitcode(self.net.h1)

    def _test_console_logger_logs_command(self, host, background):
        log = []
        def logger(line):
            log.append(line)

        # Run a simple command to completion
        cmd = 'true'
        self.assertEqual(len(log), 0)
        self.net.popen(host, cmd, background=background, console_logger=logger)
        self.assertEqual(len(log), 1)

        # Check the prefix and suffix of the logged command
        if host is not None:
            self.assertIn(host.name, log[0])
        if background:
            self.assertIn('&', log[0])
        else:
            self.assertNotIn('&', log[0])

    def test_console_logger_logs_command(self):
        self._test_console_logger_logs_command(None, False)
        self._test_console_logger_logs_command(self.net.h1, False)
        self._test_console_logger_logs_command(self.net.h1, True)

    def _test_console_logger_logs_stdout_and_stderr(self, host):
        log = []
        def logger(line):
            log.append(line)

        def popen(stdout, stderr):
            stdout_cmd = f'echo stdout'
            stderr_cmd = f'ls nonexistent_stderr_file_name_1234'
            self.net.popen(host, stdout_cmd, console_logger=logger,
                stdout=stdout, stderr=stderr, raise_error=False)
            self.net.popen(host, stderr_cmd, console_logger=logger,
                stdout=stdout, stderr=stderr, raise_error=False)

        def count_string(log, string):
            log = filter(lambda line: 'echo' not in line, log)
            log = filter(lambda line: 'ls ' not in line, log)
            log = filter(lambda line: string in line, log)
            return len(list(log))

        # Log neither stdout nor stderr
        popen(stdout=False, stderr=False)
        self.assertEqual(len(log), 2, log)
        self.assertEqual(count_string(log, 'stdout'), 0, log)
        self.assertEqual(count_string(log, 'stderr'), 0, log)

        # Log stdout only
        popen(stdout=True, stderr=False)
        self.assertEqual(len(log), 5, log)
        self.assertEqual(count_string(log, 'stdout'), 1, log)
        self.assertEqual(count_string(log, 'stderr'), 0, log)

        # Log stderr only
        popen(stdout=False, stderr=True)
        self.assertEqual(len(log), 8, log)
        self.assertEqual(count_string(log, 'stdout'), 1, log)
        self.assertEqual(count_string(log, 'stderr'), 1, log)

        # Log both stdout and stderr
        popen(stdout=True, stderr=True)
        self.assertEqual(len(log), 12, log)
        self.assertEqual(count_string(log, 'stdout'), 2, log)
        self.assertEqual(count_string(log, 'stderr'), 2, log)

    def test_console_logger_logs_stdout_and_stderr(self):
        self._test_console_logger_logs_stdout_and_stderr(None)
        self._test_console_logger_logs_stdout_and_stderr(self.net.h1)

    def test_stop_background_processes(self):
        host = self.net.h1
        cmd = 'sleep 60'

        def count_active_background_processes():
            processes = self.net.background_processes
            processes = filter(lambda p: p.returncode is None, processes)
            return len(list(processes))

        def count_active_background_threads():
            threads = self.net.background_threads
            threads = filter(lambda t: t.is_alive(), threads)
            return len(list(threads))

        # Start two background processes
        self.assertEqual(len(self.net.background_processes), 0)
        self.assertEqual(len(self.net.background_threads), 0)
        p1, t1 = self.net.popen(host, cmd, background=True)
        self.assertEqual(len(self.net.background_processes), 1)
        self.assertEqual(len(self.net.background_threads), 1)
        p2, t2 = self.net.popen(host, cmd, background=True)
        self.assertEqual(len(self.net.background_processes), 2)
        self.assertEqual(len(self.net.background_threads), 2)
        self.assertIsNone(p1.returncode, 'p1 is still running')
        self.assertIsNone(p2.returncode, 'p2 is still running')
        self.assertTrue(t1.is_alive(), 't1 is still alive')
        self.assertTrue(t2.is_alive(), 't2 is still alive')
        self.assertEqual(count_active_background_processes(), 2)
        self.assertEqual(count_active_background_threads(), 2)

        # Terminate one background process
        p1.terminate()
        p1.wait()
        t1.join()
        self.assertEqual(count_active_background_processes(), 1)
        self.assertEqual(count_active_background_threads(), 1)

        # Stop the entire emulation
        self.net.stop()
        self.stopped = True
        self.assertEqual(count_active_background_processes(), 0)
        self.assertEqual(count_active_background_threads(), 0)

    def _test_callback_function(self, host, background, seq=10):
        # Define the callback function. The function can interact with objects
        # passed by reference from outside the function.
        total_even = [0]
        def count_even(line):
            total_even[0] += (int(line) + 1) % 2

        # Execute the process and run to completion
        self.assertEqual(total_even[0], 0)
        cmd = f'seq {seq}'
        p = self.net.popen(host, cmd, background=background, func=count_even)
        if background:
            p[0].wait()
            p[1].join()
        self.assertEqual(total_even[0], seq // 2)

    def test_callback_function(self):
        self._test_callback_function(self.net.h1, False)
        self._test_callback_function(self.net.h1, True)

    def _test_appends_output_to_logfile(self, background: bool):
        host = self.net.h1
        logfile = tempfile.NamedTemporaryFile()

        def popen():
            stdout_cmd = f'echo stdout'
            stderr_cmd = f'ls nonexistent_stderr_file_name_1234'
            p1 = self.net.popen(host, stdout_cmd, background=background,
                    logfile=logfile.name, raise_error=False)
            p2 = self.net.popen(host, stderr_cmd, background=background,
                    logfile=logfile.name, raise_error=False)
            if background:
                p1[0].wait()
                p2[0].wait()
                p1[1].join()
                p2[1].join()

        def count_string(log, string):
            log = filter(lambda line: string in line, log)
            return len(list(log))

        # Contents from both stdout and stderr should be written to the logfile
        popen()
        with open(logfile.name, 'r') as f:
            contents_after_one_run = f.readlines()
        self.assertEqual(count_string(contents_after_one_run, 'stdout'), 1,
            contents_after_one_run)
        self.assertEqual(count_string(contents_after_one_run, 'stderr'), 1,
            contents_after_one_run)

        # Contents should be appended to the logfile on the second run
        popen()
        with open(logfile.name, 'r') as f:
            contents_after_two_runs = f.readlines()
        self.assertEqual(count_string(contents_after_two_runs, 'stdout'), 2,
            contents_after_two_runs)
        self.assertEqual(count_string(contents_after_two_runs, 'stderr'), 2,
            contents_after_two_runs)

    def test_appends_output_to_logfile(self):
        self._test_appends_output_to_logfile(background=False)
        self._test_appends_output_to_logfile(background=True)

    def test_perf_report(self):
        host = self.net.h1
        with tempfile.TemporaryDirectory() as tempdir:
            # Non-background process
            logfile = os.path.join(tempdir, 'p1.log')
            self.assertFalse(self.net.perf)
            self.net.popen(host, 'ls', background=False, logfile=logfile)
            self.net.perf = True
            self.assertFalse(os.path.exists(f'{logfile}.perf'), 'perf file not created')
            self.net.popen(host, 'ls', background=False, logfile=logfile)
            self.assertTrue(os.path.exists(f'{logfile}.perf'), 'perf file created')

            # Background process
            logfile = os.path.join(tempdir, 'p2.log')
            p = self.net.popen(host, 'yes', background=True, logfile=logfile)
            time.sleep(0.1)
            self.stopNetwork()
            self.assertTrue(os.path.exists(f'{logfile}.perf'),
                'perf file created for background process')

    def test_rust_debug_log_level(self):
        host = self.net.h1
        cmd = f'../quacker/target/release/quacker '\
              f'--interface h1-eth0 --target-addr {self.net.h2.IP()}:5252'

        with tempfile.NamedTemporaryFile() as logfile:
            self.net.debug = False
            self.net.popen(host, cmd, timeout=0.1, logfile=logfile.name)
            lines = logfile.read()
            self.assertIn(b'INFO', lines, lines)
            self.assertNotIn(b'DEBUG', lines, lines)

        with tempfile.NamedTemporaryFile() as logfile:
            self.net.debug = True
            self.net.popen(host, cmd, timeout=0.1, logfile=logfile.name)
            lines = logfile.read()
            self.assertIn(b'INFO', lines, lines)
            self.assertIn(b'DEBUG', lines, lines)


class TestProxyFunctions(NetworkTestCase):
    def setUp(self):
        super().setUp()
        self._logdir = tempfile.TemporaryDirectory()
        self.logfile = f'{self._logdir.name}/{ROUTER_LOGFILE}'

    def tearDown(self):
        super().tearDown()
        self._logdir.cleanup()

    def test_start_tcp_pep(self):
        net = self.setUpOneHopNetwork()
        self.assertFalse(os.path.exists(self.logfile))
        net.start_tcp_pep(logfile=self.logfile, timeout=2)
        output = net.p1.cmd('ps aux | grep pep')
        self.assertIn('pepsal', output, 'tcp pep started')
        self.stopNetwork()  # flush processes
        self.assertTrue(os.path.exists(self.logfile))
        with open(self.logfile, 'r') as f:
            self.assertNotEqual(f.read(), '', 'proxy writes to logfile')
