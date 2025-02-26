"""
Test benchmark/media_benchmark.py.
"""
import sys
import os
import tempfile

import unittest

from network import OneHopNetwork
from benchmark import *


class MediaTestCase(unittest.TestCase):
    def setUp(self):
        # Suppress stderr logging from network setup
        self._stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')

        # Run tests from the upper-level directory (the sidekick home)
        self._cwd = os.getcwd()
        os.chdir('..')

        # Setup a mininet network
        self.stopped = True
        self.setUpOneHopNetwork()

        # Set default parameters
        self.label = 'my_benchmark'
        self.duration = 1
        self.frequency = 20

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

    def setUpOneHopNetwork(
        self, delay1=1, delay2=10, loss1=0, loss2=0, bw1=50, bw2=10,
        jitter1=None, jitter2=None, qdisc='red', pacing=False,
        bridge_proxy=True
    ) -> OneHopNetwork:
        self.stopNetwork()
        self.net = OneHopNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                                 jitter1, jitter2, qdisc, pacing, bridge_proxy)
        self.stopped = False

    def setUpMediaBenchmark(self) -> MediaBenchmark:
        bm = MediaBenchmark(
            self.net, self.label, self.duration, self.frequency, self.logdir,
            proxy_type=None,
        )
        return bm


class TestConstructor(MediaTestCase):
    def test_common_properties(self):
        bm = self.setUpMediaBenchmark()
        self.assertEqual(bm.net, self.net)

        # Test basic property methods
        self.assertEqual(bm.label, self.label)
        self.assertEqual(bm.duration, self.duration)

        # Test mininet host property methods
        self.assertEqual(bm.client, self.net.h1)
        self.assertEqual(bm.server, self.net.h2)
        self.assertEqual(bm.proxy, self.net.p1)
        self.assertEqual(bm.logfile(bm.client), f'{self.logdir}/{CLIENT_LOGFILE}')
        self.assertEqual(bm.logfile(bm.server), f'{self.logdir}/{SERVER_LOGFILE}')
        self.assertEqual(bm.logfile(bm.proxy), f'{self.logdir}/{ROUTER_LOGFILE}')


class TestEndpoints(MediaTestCase):
    def test_start_server(self):
        """The server starts successfully without hanging, and can be found to
        be listening on a specific port. The server also writes to a logfile.
        """
        port = 5201
        bm = self.setUpMediaBenchmark()
        server_logfile = bm.logfile(bm.server)
        output = bm.server.cmd(f'lsof -i :{port}')
        self.assertEqual(output, '', 'server is not running initially')
        self.assertFalse(os.path.exists(server_logfile))
        bm.start_server()
        output = bm.server.cmd(f'lsof -i :{port}')
        self.assertNotEqual(output, '', 'server should have started')
        self.stopNetwork()  # Give background processes a chance to flush
        self.assertTrue(os.path.exists(server_logfile))
        with open(server_logfile, 'r') as f:
            self.assertNotEqual(f.read(), '', 'server writes to logfile')

    def test_run_client(self):
        """The client makes a request to the server and returns a result.
        """
        bm = self.setUpMediaBenchmark()
        bm.start_server()
        client_logfile = bm.logfile(bm.client)
        self.assertFalse(os.path.exists(client_logfile))
        result = bm.run_client()
        self.assertIsNotNone(result)
        self.assertGreater(result.time_s, 0)
        self.assertGreater(len(result.client_latencies), 0)
        self.assertGreater(len(result.server_latencies), 0)
        self.assertTrue(os.path.exists(client_logfile))
        with open(client_logfile, 'r') as f:
            self.assertNotEqual(f.read(), '', 'client writes to logfile')


class TestRunBenchmark(MediaTestCase):
    def run_benchmark(self, bm, num_trials) -> dict:
        result = bm.run_benchmark(num_trials)
        result = json.loads(result.json())
        return result

    def _test_run_benchmark(self, bm, num_trials, additional_data=None):
        """The benchmark runs and returns successful results for the given
        number of trials.
        """
        result = self.run_benchmark(bm, num_trials)

        # Validate inputs
        inputs = result['inputs']
        self.assertEqual(inputs.get('label'), self.label)
        self.assertEqual(inputs.get('protocol'), 'media')
        self.assertEqual(inputs.get('num_trials'), num_trials)
        self.assertEqual(inputs.get('proxy_type'), 'none')

        # Validate outputs
        outputs = result['outputs']
        self.assertEqual(len(outputs), num_trials)
        for output in outputs:
            self.assertTrue(output.get('success'))
            self.assertGreater(output.get('time_s'), 0)
            self.assertLess(output.get('time_s'), 10, 'sanity check runtime')
            self.assertGreater(len(output.get('client_latencies')), 0)
            self.assertGreater(len(output.get('server_latencies')), 0)
            self.assertIsNone(output.get('statistics'))
            self.assertEqual(output.get('additional_data'), additional_data)

    def test_run_benchmark_one_trial(self):
        bm = self.setUpMediaBenchmark()
        self._test_run_benchmark(bm, 1)

    def test_run_benchmark_multiple_trials(self):
        bm = self.setUpMediaBenchmark()
        self._test_run_benchmark(bm, 2)
