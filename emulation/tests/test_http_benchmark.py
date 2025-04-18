"""
Test benchmark/http_benchmark.py.
"""
import sys
import os
import tempfile

import unittest

from network import OneHopNetwork
from benchmark import *


class HTTPDownloadTestCase(unittest.TestCase):
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
        self.data_size = 1000
        self.cca = 'cubic'
        self.certfile = 'deps/certs/out/leaf_cert.pem'
        self.keyfile = 'deps/certs/out/leaf_cert.key'

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
    ) -> OneHopNetwork:
        if self.stopped:
            if not self.stopped:
                self.stopNetwork()
            self.net = OneHopNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                                     jitter1, jitter2, qdisc, pacing)
            self.stopped = False

    def setUpTCPBenchmark(self, proxy_type=None) -> TCPBenchmark:
        bm = TCPBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, proxy_type,
        )
        return bm

    def setUpGoogleQUICBenchmark(self, proxy_type=None) -> GoogleQUICBenchmark:
        self.keyfile = 'deps/certs/out/leaf_cert.pkcs8'
        bm = GoogleQUICBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, proxy_type,
        )
        return bm

    def setUpCloudflareQUICBenchmark(
        self, port: int=4433, proxy_type=None,
    ) -> CloudflareQUICBenchmark:
        bm = CloudflareQUICBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, port=port, proxy_type=proxy_type,
        )
        return bm

    # def setUpPicoQUICBenchmark(self, port: int=4433) -> PicoQUICBenchmark:
    def setUpPicoQUICBenchmark(
        self, ack_delay: int=0, port: int=4433, proxy_type=None,
    ) -> PicoQUICBenchmark:
        bm = PicoQUICBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, ack_delay=ack_delay,
            port=port, proxy_type=proxy_type,
        )
        return bm


class TestConstructors(HTTPDownloadTestCase):
    def _test_common_properties(self, bm):
        self.assertEqual(bm.net, self.net)

        # Test basic property methods
        self.assertEqual(bm.label, self.label)
        self.assertEqual(bm.data_size, self.data_size)
        self.assertEqual(bm.cca, self.cca)
        self.assertEqual(bm.certfile, self.certfile)
        self.assertEqual(bm.keyfile, self.keyfile)

        # Test mininet host property methods
        self.assertEqual(bm.client, self.net.h1)
        self.assertEqual(bm.server, self.net.h2)
        self.assertEqual(bm.proxy, self.net.p1)
        self.assertEqual(bm.logfile(bm.client), f'{self.logdir}/{CLIENT_LOGFILE}')
        self.assertEqual(bm.logfile(bm.server), f'{self.logdir}/{SERVER_LOGFILE}')
        self.assertEqual(bm.logfile(bm.proxy), f'{self.logdir}/{ROUTER_LOGFILE}')

    def test_tcp_constructor(self):
        bm = self.setUpTCPBenchmark()
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.TCP)
        self.assertIsNone(bm.proxy_type)

    @unittest.skip('skip chromium tests')
    def test_google_quic_constructor(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.GOOGLE_QUIC)
        self.assertIsNone(bm.proxy_type)

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_constructor(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.CLOUDFLARE_QUIC)
        self.assertIsNone(bm.proxy_type)

    def test_picoquic_constructor(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.PICOQUIC)
        self.assertIsNone(bm.proxy_type)

    def test_constructors_with_proxies(self):
        bm = self.setUpTCPBenchmark(proxy_type=ProxyType.PEPSAL)
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.TCP)
        self.assertEqual(bm.proxy_type, ProxyType.PEPSAL)

        bm = self.setUpPicoQUICBenchmark(proxy_type=ProxyType.SIDEKICK)
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.PICOQUIC)
        self.assertEqual(bm.proxy_type, ProxyType.SIDEKICK)

        bm = self.setUpPicoQUICBenchmark(proxy_type=ProxyType.PICOQUIC)
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.PICOQUIC)
        self.assertEqual(bm.proxy_type, ProxyType.PICOQUIC)




class TestStartServer(HTTPDownloadTestCase):
    def _test_start_server(self, bm, port):
        """The server starts successfully without hanging, and can be found to
        be listening on a specific port. The server also writes to a logfile.
        """
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

    def test_tcp_start_server(self):
        bm = self.setUpTCPBenchmark()
        self._test_start_server(bm, 8443)

    @unittest.skip('skip chromium tests')
    def test_google_quic_start_server(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_start_server(bm, 6121)

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_start_server(self):
        port = 1234
        bm = self.setUpCloudflareQUICBenchmark(port=port)
        self._test_start_server(bm, port)

    def test_picoquic_start_server(self):
        port = 4321
        bm = self.setUpPicoQUICBenchmark(port=port)
        self._test_start_server(bm, port)


class TestRunClient(HTTPDownloadTestCase):
    def _test_run_client(self, bm):
        """The client makes a request to the server and returns a result with
        a successful HTTP status code and positive runtime.
        """
        bm.start_server()
        client_logfile = bm.logfile(bm.client)
        self.assertFalse(os.path.exists(client_logfile))
        result = bm.run_client(timeout=None)
        self.assertIsNotNone(result)
        self.assertEqual(result.status_code, HTTP_OK_STATUSCODE)
        self.assertGreater(result.time_s, 0)
        self.assertTrue(os.path.exists(client_logfile))
        with open(client_logfile, 'r') as f:
            self.assertNotEqual(f.read(), '', 'client writes to logfile')

    def test_tcp_run_client(self):
        bm = self.setUpTCPBenchmark()
        self._test_run_client(bm)

    @unittest.skip('skip chromium tests')
    def test_google_quic_run_client(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_client(bm)

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_run_client(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_client(bm)

    def test_picoquic_run_client(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_run_client(bm)


class TestRunBenchmark(HTTPDownloadTestCase):
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
        self.assertEqual(inputs.get('protocol'), bm.protocol.name)
        self.assertEqual(inputs.get('num_trials'), num_trials)
        self.assertEqual(inputs.get('data_size'), self.data_size)
        self.assertEqual(inputs.get('cca'), self.cca)
        self.assertEqual(inputs.get('proxy_type'), 'none')

        # Validate outputs
        outputs = result['outputs']
        self.assertEqual(len(outputs), num_trials)
        for output in outputs:
            self.assertTrue(output.get('success'))
            self.assertFalse(output.get('timeout'))
            self.assertGreater(output.get('time_s'), 0)
            self.assertLess(output.get('time_s'), 10, 'sanity check runtime')
            self.assertGreater(output.get('throughput_mbps'), 0)
            self.assertIsNone(output.get('statistics'))
            self.assertEqual(output.get('additional_data'), additional_data)

    def test_tcp_run_benchmark_one_trial(self):
        self.setUpOneHopNetwork()
        bm = self.setUpTCPBenchmark()
        self._test_run_benchmark(bm, 1)

    def test_tcp_run_benchmark_multiple_trials(self):
        self.setUpOneHopNetwork()
        bm = self.setUpTCPBenchmark()
        self._test_run_benchmark(bm, 2)

    @unittest.skip('skip chromium tests')
    def test_google_quic_run_benchmark_one_trial(self):
        self.setUpOneHopNetwork()
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_benchmark(bm, 1)

    @unittest.skip('skip chromium tests')
    def test_google_quic_run_benchmark_multiple_trials(self):
        self.setUpOneHopNetwork()
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_benchmark(bm, 2)

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_run_benchmark_one_trial(self):
        self.setUpOneHopNetwork()
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_benchmark(bm, 1)

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_run_benchmark_multiple_trials(self):
        self.setUpOneHopNetwork()
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_benchmark(bm, 2)

    def test_picoquic_run_benchmark_one_trial(self):
        self.setUpOneHopNetwork()
        bm = self.setUpPicoQUICBenchmark()
        additional_data = {
            'num_spurious_sender': 0,
            'num_spurious_receiver': 0,
        }
        self._test_run_benchmark(bm, 1, additional_data=additional_data)

    def test_picoquic_run_benchmark_multiple_trials(self):
        self.setUpOneHopNetwork()
        bm = self.setUpPicoQUICBenchmark()
        additional_data = {
            'num_spurious_sender': 0,
            'num_spurious_receiver': 0,
        }
        self._test_run_benchmark(bm, 5, additional_data=additional_data)
