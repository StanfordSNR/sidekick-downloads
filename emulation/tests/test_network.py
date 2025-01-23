import unittest
import time
import tempfile
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

    def setUpOneHopNetwork(
        self, delay1=1, delay2=10, loss1=0, loss2=0, bw1=50, bw2=10,
        jitter1=None, jitter2=None, qdisc='red', pacing=False, setup_time=0,
    ) -> OneHopNetwork:
        net = OneHopNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                            jitter1, jitter2, qdisc, pacing)
        if setup_time > 0:
            time.sleep(setup_time)
        return net

    def setUpDirectNetwork(
        self, delay=10, loss=0, bw=10, jitter=None, qdisc='red', pacing=False,
        setup_time=0,
    ) -> DirectNetwork:
        net = DirectNetwork(delay, loss, bw, jitter, qdisc, pacing)
        if setup_time > 0:
            time.sleep(setup_time)
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
        net.stop()

    def test_one_hop_proxy_is_reachable(self):
        net = self.setUpOneHopNetwork()
        self.assertReachable(net.r1, net.h1)
        self.assertReachable(net.r1, net.h2)
        self.assertReachable(net.h1, net.r1)
        self.assertReachable(net.h2, net.r1)
        net.stop()

    def test_direct_hosts_are_reachable(self):
        net = self.setUpDirectNetwork()
        self.assertReachable(net.h1, net.h2)
        self.assertReachable(net.h2, net.h1)
        net.stop()


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
        net.stop()

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
        net.stop()


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
        net.stop()

    @unittest.skip('pings are flaky when there is loss')
    def test_one_hop_loss_config(self):
        net = self.setUpOneHopNetwork(loss1=20, loss2=20, setup_time=2)
        for (node1, node2) in [
            (net.h1, net.h2),
            (net.h1, net.r1),
            (net.r1, net.h2),
        ]:
            self.assertLossIsCorrect(node1, node2, True)
            self.assertLossIsCorrect(node2, node1, True)
        net.stop()

    @unittest.skip('pings are flaky when there is loss')
    def test_one_hop_asymmetric_loss_config(self):
        net = self.setUpOneHopNetwork(loss1=20, loss2=0, setup_time=2)
        for (node1, node2, loss) in [
            (net.h1, net.h2, True),
            (net.h1, net.r1, True),
            (net.r1, net.h2, False),
        ]:
            self.assertLossIsCorrect(node1, node2, loss)
            self.assertLossIsCorrect(node2, node1, loss)
        net.stop()


class TestBandwidthConfig(NetworkTestCase):
    pass


class TestQdiscConfig(NetworkTestCase):
    pass


class TestSetTCPCongestionControl(NetworkTestCase):
    def setUp(self):
        super().setUp()
        self.net1 = self.setUpDirectNetwork()
        self.net2 = self.setUpOneHopNetwork()

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
        self.assertCCAEquals(self.net2.r1, expected_cca)

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
        self.net = self.setUpDirectNetwork()
        self.stopped = False

    def tearDown(self):
        if not self.stopped:
            self.net.stop()
            self.stopped = True

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
