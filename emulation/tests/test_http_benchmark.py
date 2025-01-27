"""
Test benchmark/http_benchmark.py.
"""
import sys
import os
import tempfile

import unittest
from unittest.mock import patch

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
        self.net = self.setUpOneHopNetwork()
        self.stopped = False

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
        net = OneHopNetwork(delay1, delay2, loss1, loss2, bw1, bw2,
                            jitter1, jitter2, qdisc, pacing)
        return net

    def setUpTCPBenchmark(self, pep=False, sidekick=False) -> TCPBenchmark:
        bm = TCPBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, pep=pep, sidekick=sidekick,
        )
        return bm

    def setUpGoogleQUICBenchmark(self, sidekick=False) -> GoogleQUICBenchmark:
        self.keyfile = 'deps/certs/out/leaf_cert.pkcs8'
        bm = GoogleQUICBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, sidekick=sidekick,
        )
        return bm

    def setUpCloudflareQUICBenchmark(
        self, port: int=4433, sidekick=False
    ) -> CloudflareQUICBenchmark:
        bm = CloudflareQUICBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, port=port, sidekick=sidekick,
        )
        return bm

    # def setUpPicoQUICBenchmark(self, port: int=4433) -> PicoQUICBenchmark:
    def setUpPicoQUICBenchmark(
        self, port: int=4433, sidekick=False
    ) -> PicoQUICBenchmark:
        bm = PicoQUICBenchmark(
            self.net, self.label, self.data_size, self.cca, self.certfile,
            self.keyfile, self.logdir, port=port, sidekick=sidekick,
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

    def test_google_quic_constructor(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.GOOGLE_QUIC)
        self.assertIsNone(bm.proxy_type)

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
        bm = self.setUpTCPBenchmark(pep=True)
        self._test_common_properties(bm)
        self.assertEqual(bm.protocol, Protocol.TCP)
        self.assertEqual(bm.proxy_type, ProxyType.PEPSAL)


class TestStartServer(HTTPDownloadTestCase):
    def _test_server_is_listening_on(self, bm, port):
        """The server starts successfully without hanging, and can be found to
        be listening on a specific port.
        """
        output = bm.server.cmd(f'lsof -i :{port}')
        self.assertEqual(output, '', 'server is not running initially')
        bm.start_server()
        output = bm.server.cmd(f'lsof -i :{port}')
        self.assertNotEqual(output, '', 'server should have started')

    def test_tcp_server_is_listening(self):
        bm = self.setUpTCPBenchmark()
        self._test_server_is_listening_on(bm, 8443)

    def test_google_quic_server_is_listening(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_server_is_listening_on(bm, 6121)

    def test_cloudflare_quic_server_is_listening(self):
        port = 1234
        bm = self.setUpCloudflareQUICBenchmark(port=port)
        self._test_server_is_listening_on(bm, port)

    def test_picoquic_server_is_listening(self):
        port = 4321
        bm = self.setUpPicoQUICBenchmark(port=port)
        self._test_server_is_listening_on(bm, port)


class TestRunClient(HTTPDownloadTestCase):
    def _test_client_returns_result(self, bm):
        """The client makes a request to the server and returns a result with
        a successful HTTP status code and positive runtime.
        """
        bm.start_server()
        result = bm.run_client(timeout=None)
        self.assertIsNotNone(result)
        http_status_code, total_time = result
        self.assertEqual(http_status_code, HTTP_OK_STATUSCODE)
        self.assertGreater(total_time, 0)

    def test_tcp_client_returns_result(self):
        bm = self.setUpTCPBenchmark()
        self._test_client_returns_result(bm)

    def test_google_quic_client_returns_result(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_client_returns_result(bm)

    def test_cloudflare_quic_client_returns_result(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_client_returns_result(bm)

    def test_picoquic_client_returns_result(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_client_returns_result(bm)


class TestRunBenchmark(HTTPDownloadTestCase):
    def run_benchmark(self, bm, num_trials) -> dict:
        result = bm.run_benchmark(num_trials)
        result = json.loads(result.json())
        return result

    def _test_run_benchmark(self, bm, num_trials):
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
            self.assertIsNone(output.get('additional_data'))

    def test_tcp_run_benchmark_one_trial(self):
        bm = self.setUpTCPBenchmark()
        self._test_run_benchmark(bm, 1)

    def test_tcp_pep_run_benchmark_one_trial(self):
        bm = self.setUpTCPBenchmark(pep=True)
        self._test_run_benchmark(bm, 1)

    def test_tcp_sidekick_run_benchmark_one_trial(self):
        bm = self.setUpTCPBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 1)

    def test_tcp_run_benchmark_multiple_trials(self):
        bm = self.setUpTCPBenchmark()
        self._test_run_benchmark(bm, 5)

    def test_tcp_pep_run_benchmark_multiple_trial(self):
        bm = self.setUpTCPBenchmark(pep=True)
        self._test_run_benchmark(bm, 5)

    def test_tcp_sidekick_run_benchmark_multiple_trial(self):
        bm = self.setUpTCPBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 5)

    def test_google_quic_run_benchmark_one_trial(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_benchmark(bm, 1)

    def test_google_quic_sidekick_run_benchmark_one_trial(self):
        bm = self.setUpGoogleQUICBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 1)

    def test_google_quic_run_benchmark_multiple_trials(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_benchmark(bm, 5)

    def test_google_quic_sidekick_run_benchmark_multiple_trials(self):
        bm = self.setUpGoogleQUICBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 5)

    def test_cloudflare_quic_run_benchmark_one_trial(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_benchmark(bm, 1)

    def test_cloudflare_quic_sidekick_run_benchmark_one_trial(self):
        bm = self.setUpCloudflareQUICBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 1)

    def test_cloudflare_quic_run_benchmark_multiple_trials(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_benchmark(bm, 5)

    def test_cloudflare_quic_sidekick_run_benchmark_multiple_trials(self):
        bm = self.setUpCloudflareQUICBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 5)

    def test_picoquic_run_benchmark_one_trial(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_run_benchmark(bm, 1)

    def test_picoquic_sidekick_run_benchmark_one_trial(self):
        bm = self.setUpPicoQUICBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 1)

    def test_picoquic_run_benchmark_multiple_trials(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_run_benchmark(bm, 5)

    def test_picoquic_sidekick_run_benchmark_multiple_trials(self):
        bm = self.setUpPicoQUICBenchmark(sidekick=True)
        self._test_run_benchmark(bm, 5)

    def _test_hosts_write_to_logs(self, bm, proxy: bool):
        self.run_benchmark(bm, 1)
        self.stopNetwork()  # Give background processes a chance to flush
        with open(bm.logfile(bm.client), 'r') as f:
            self.assertNotEqual(f.read(), '', 'client writes to logfile')
        with open(bm.logfile(bm.server), 'r') as f:
            self.assertNotEqual(f.read(), '', 'server writes to logfile')
        router_logfile = bm.logfile(bm.proxy)
        if proxy:
            self.assertTrue(os.path.exists(router_logfile))
            with open(router_logfile, 'r') as f:
                self.assertNotEqual(f.read(), '', 'proxy writes to logfile')
        else:
            self.assertFalse(os.path.exists(router_logfile))

    def test_tcp_hosts_write_to_logs(self):
        bm = self.setUpTCPBenchmark()
        self._test_hosts_write_to_logs(bm, False)

    def test_tcp_pep_hosts_write_to_logs(self):
        bm = self.setUpTCPBenchmark(pep=True)
        self._test_hosts_write_to_logs(bm, True)

    def test_google_quic_hosts_write_to_logs(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_hosts_write_to_logs(bm, False)

    def test_cloudflare_quic_hosts_write_to_logs(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_hosts_write_to_logs(bm, False)

    @unittest.expectedFailure
    def test_picoquic_hosts_write_to_logs(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_hosts_write_to_logs(bm, False)


class TestStartProxy(HTTPDownloadTestCase):
    @patch.object(EmulatedNetwork, 'start_tcp_pep')
    def test_tcp_start_proxy(self, mock_start_tcp_pep):
        # NOTE(gina): Tried to not mock the function at first and use ps
        # to ascertain whether a pepsal process was started. However, I
        # couldn't identify such a process even though the pepsal background
        # process in start_tcp_pep started successfully without a timeout.

        # The start_proxy function is a no-op without a proxy type
        bm = self.setUpTCPBenchmark(pep=False)
        mock_start_tcp_pep.assert_not_called()
        bm.start_proxy()
        mock_start_tcp_pep.assert_not_called()

        # The start_proxy function calls start_tcp_pep with a pepsal proxy
        bm = self.setUpTCPBenchmark(pep=True)
        mock_start_tcp_pep.assert_not_called()
        bm.start_proxy()
        mock_start_tcp_pep.assert_called_once()
