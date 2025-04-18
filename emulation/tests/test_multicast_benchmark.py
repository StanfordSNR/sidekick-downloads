"""
Test benchmark/multicast_benchmark.py.
"""
import sys
import os
import tempfile

import unittest

from network import MulticastNetwork
from benchmark import *


class MulticastTestCase(unittest.TestCase):
    def setUp(self):
        # Suppress stderr logging from network setup
        self._stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')

        # Run tests from the upper-level directory (the sidekick home)
        self._cwd = os.getcwd()
        os.chdir('..')

        # Setup a mininet network
        self.stopped = True

        # Set default parameters
        self.label = 'my_benchmark'
        self.duration = 1
        self.frequency = 20
        self.nack_delay = 0
        self.port = 5202

        # Setup logfiles
        self._logdir = tempfile.TemporaryDirectory()
        self.logdir = self._logdir.name

    def tearDown(self):
        self._logdir.cleanup()
        self.stopNetwork()
        os.chdir(self._cwd)

    def stopNetwork(self):
        if not self.stopped:
            self.net.stop()
            self.stopped = True

    def setUpMulticastNetwork(
        self, num_clients, delay1=1, delay2=10, loss1=0, loss2=0,
        bw1=50, bw2=10, qdisc='red', pacing=False, proxy=None,
    ) -> MulticastNetwork:
        self.stopNetwork()
        self.net = MulticastNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                                    qdisc, pacing, num_clients, proxy=proxy)
        self.stopped = False

    def setUpMulticastBenchmark(self, num_clients) -> MulticastBenchmark:
        self.setUpMulticastNetwork(num_clients)
        bm = MulticastBenchmark(
            self.net, self.label, self.duration, self.frequency, self.logdir,
            port=self.port, num_clients=num_clients, nack_delay=self.nack_delay,
            proxy_type=None,
        )
        return bm


class TestConstructor(MulticastTestCase):
    def test_common_properties(self):
        bm = self.setUpMulticastBenchmark(3)
        self.assertEqual(bm.net, self.net)

        # Test basic property methods
        self.assertEqual(bm.label, self.label)
        self.assertEqual(bm.duration, self.duration)
        self.assertEqual(bm.frequency, self.frequency)
        self.assertEqual(bm.nack_delay, self.nack_delay)
        self.assertEqual(bm.num_clients, 3)

        # Test mininet host property methods
        self.assertEqual(bm.clients, self.net.clients)
        self.assertEqual(bm.server, self.net.server)
        self.assertEqual(bm.proxy, self.net.p1)
        self.assertEqual(bm.logfile(bm.clients[0]), f'{self.logdir}/{CLIENT_LOGFILE}.1')
        self.assertEqual(bm.logfile(bm.clients[1]), f'{self.logdir}/{CLIENT_LOGFILE}.2')
        self.assertEqual(bm.logfile(bm.clients[2]), f'{self.logdir}/{CLIENT_LOGFILE}.3')
        self.assertEqual(bm.logfile(bm.server), f'{self.logdir}/{SERVER_LOGFILE}')
        self.assertEqual(bm.logfile(bm.proxy), f'{self.logdir}/{ROUTER_LOGFILE}')


class TestEndpoints(MulticastTestCase):
    def test_start_server(self):
        """The server starts successfully without hanging, and can be found to
        be listening on a specific port. The server also writes to a logfile.
        """
        bm = self.setUpMulticastBenchmark(1)
        server_logfile = bm.logfile(bm.server)
        output = bm.server.cmd(f'lsof -i :{self.port}')
        self.assertEqual(output, '', 'server is not running initially')
        self.assertFalse(os.path.exists(server_logfile))
        bm.start_server()
        output = bm.server.cmd(f'lsof -i :{self.port}')
        self.assertNotEqual(output, '', 'server should have started')
        self.stopNetwork()  # Give background processes a chance to flush
        self.assertTrue(os.path.exists(server_logfile))
        with open(server_logfile, 'r') as f:
            self.assertNotEqual(f.read(), '', 'server writes to logfile')

    def _test_run_n_clients(self, num_clients):
        """The client makes a request to the server and returns a result.
        """
        bm = self.setUpMulticastBenchmark(num_clients)
        bm.start_server()
        client_logfile = bm.logfile(bm.clients[0])
        self.assertFalse(os.path.exists(client_logfile))
        result = bm.run_client()
        self.assertIsNotNone(result)
        self.assertGreater(result.time_s, 0)
        self.assertEqual(len(result.client_ids), num_clients)
        self.assertEqual(len(set(result.client_ids)), num_clients, 'ids are unique')
        self.assertEqual(len(result.latencies), num_clients)
        for latencies in result.latencies:
            self.assertGreater(len(latencies), 0)
        self.assertEqual(len(result.num_spurious), num_clients)
        self.assertTrue(os.path.exists(client_logfile))
        with open(client_logfile, 'r') as f:
            self.assertNotEqual(f.read(), '', 'client writes to logfile')

    def test_run_one_client(self):
        self._test_run_n_clients(1)

    def test_run_multiple_clients(self):
        self._test_run_n_clients(3)


class TestRunBenchmark(MulticastTestCase):
    def run_benchmark(self, bm, num_trials) -> dict:
        result = bm.run_benchmark(num_trials)
        result = json.loads(result.json())
        return result

    def _test_run_benchmark(self, num_clients, num_trials, additional_data=None):
        """The benchmark runs and returns successful results for the given
        number of trials.
        """
        bm = self.setUpMulticastBenchmark(num_clients)
        result = self.run_benchmark(bm, num_trials)

        # Validate inputs
        inputs = result['inputs']
        self.assertEqual(inputs.get('label'), self.label)
        self.assertEqual(inputs.get('protocol'), 'multicast')
        self.assertEqual(inputs.get('num_trials'), num_trials)
        self.assertEqual(inputs.get('proxy_type'), 'none')

        # Validate outputs
        outputs = result['outputs']
        self.assertEqual(len(outputs), num_trials)
        for output in outputs:
            self.assertTrue(output.get('success'))
            self.assertGreater(output.get('time_s'), 0)
            self.assertLess(output.get('time_s'), 10, 'sanity check runtime')
            self.assertEqual(len(output.get('client_ids')), num_clients)
            self.assertEqual(len(output.get('latencies')), num_clients)
            self.assertEqual(len(output.get('num_spurious')), num_clients)
            self.assertIsNone(output.get('statistics'))
            self.assertEqual(output.get('additional_data'), additional_data)

    def test_run_benchmark_one_trial(self):
        self._test_run_benchmark(num_clients=3, num_trials=1)

    def test_run_benchmark_multiple_trials(self):
        self._test_run_benchmark(num_clients=3, num_trials=2)
