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

    def setUpTCPBenchmark(self, pep=False) -> TCPBenchmark:
        bm = TCPBenchmark(
            self.net, self.data_size, self.cca, pep, self.certfile,
            self.keyfile,
        )
        return bm

    def setUpGoogleQUICBenchmark(self) -> GoogleQUICBenchmark:
        self.keyfile = 'deps/certs/out/leaf_cert.pkcs8'
        bm = GoogleQUICBenchmark(
            self.net, self.data_size, self.cca, self.certfile, self.keyfile,
        )
        return bm

    def setUpCloudflareQUICBenchmark(self) -> CloudflareQUICBenchmark:
        bm = CloudflareQUICBenchmark(
            self.net, self.data_size, self.cca, self.certfile, self.keyfile,
        )
        return bm

    # def setUpPicoQUICBenchmark(self, port: int=4433) -> PicoQUICBenchmark:
    def setUpPicoQUICBenchmark(self) -> PicoQUICBenchmark:
        bm = PicoQUICBenchmark(
            self.net, self.data_size, self.cca, self.certfile, self.keyfile,
        )
        return bm


class TestConstructors(HTTPDownloadTestCase):
    def _test_common_properties(self, bm):
        self.assertEqual(bm.net, self.net)

        # Test basic property methods
        self.assertEqual(bm.data_size, self.data_size)
        self.assertEqual(bm.cca, self.cca)
        self.assertEqual(bm.certfile, self.certfile)
        self.assertEqual(bm.keyfile, self.keyfile)

        # Test mininet host property methods
        self.assertEqual(bm.client, self.net.h1)
        self.assertEqual(bm.server, self.net.h2)

    def test_tcp_constructor(self):
        bm = self.setUpTCPBenchmark()
        self._test_common_properties(bm)

    def test_google_quic_constructor(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_common_properties(bm)

    def test_cloudflare_quic_constructor(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_common_properties(bm)

    def test_picoquic_constructor(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_common_properties(bm)


class TestStartServer(HTTPDownloadTestCase):
    def _test_server_is_listening_on(self, bm, port):
        """The server starts successfully without hanging, and can be found to
        be listening on a specific port.
        """
        logfile = f'{self.logdir}/{SERVER_LOGFILE}'
        output = bm.server.cmd(f'lsof -i :{port}')
        self.assertEqual(output, '', 'server is not running initially')
        bm.start_server(logfile)
        output = bm.server.cmd(f'lsof -i :{port}')
        self.assertNotEqual(output, '', 'server should have started')

    def test_tcp_server_is_listening(self):
        bm = self.setUpTCPBenchmark()
        self._test_server_is_listening_on(bm, 8443)

    def test_google_quic_server_is_listening(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_server_is_listening_on(bm, 6121)

    def test_cloudflare_quic_server_is_listening(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_server_is_listening_on(bm, 4433)

    def test_picoquic_server_is_listening(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_server_is_listening_on(bm, 4433)


class TestRunClient(HTTPDownloadTestCase):
    def _test_client_returns_result(self, bm):
        """The client makes a request to the server and returns a result with
        a successful HTTP status code and positive runtime.
        """
        server_logfile = f'{self.logdir}/{SERVER_LOGFILE}'
        client_logfile = f'{self.logdir}/{CLIENT_LOGFILE}'
        bm.start_server(server_logfile)
        result = bm.run_client(client_logfile, timeout=None)
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
        result = bm.run(self.label, self.logdir, num_trials, timeout=None,
            network_statistics=False)
        result = json.loads(result.json())
        return result

    def _test_run_benchmark(self, bm, num_trials, protocol):
        """The benchmark runs and returns successful results for the given
        number of trials.
        """
        result = self.run_benchmark(bm, num_trials)

        # Validate inputs
        inputs = result['inputs']
        self.assertEqual(inputs.get('label'), self.label)
        self.assertEqual(inputs.get('protocol'), protocol)
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
        self._test_run_benchmark(bm, 1, Protocol.TCP.name)

    def test_tcp_pep_run_benchmark_one_trial(self):
        bm = self.setUpTCPBenchmark(pep=True)
        self._test_run_benchmark(bm, 1, Protocol.TCP.name)

    def test_tcp_run_benchmark_multiple_trials(self):
        bm = self.setUpTCPBenchmark()
        self._test_run_benchmark(bm, 5, Protocol.TCP.name)

    def test_tcp_pep_run_benchmark_multiple_trial(self):
        bm = self.setUpTCPBenchmark(pep=True)
        self._test_run_benchmark(bm, 5, Protocol.TCP.name)

    def test_google_quic_run_benchmark_one_trial(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_benchmark(bm, 1, Protocol.GOOGLE_QUIC.name)

    def test_google_quic_run_benchmark_multiple_trials(self):
        bm = self.setUpGoogleQUICBenchmark()
        self._test_run_benchmark(bm, 5, Protocol.GOOGLE_QUIC.name)

    @unittest.expectedFailure
    def test_cloudflare_quic_run_benchmark_one_trial(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_benchmark(bm, 1, Protocol.CLOUDFLARE_QUIC.name)

    @unittest.expectedFailure
    def test_cloudflare_quic_run_benchmark_multiple_trials(self):
        bm = self.setUpCloudflareQUICBenchmark()
        self._test_run_benchmark(bm, 5, Protocol.CLOUDFLARE_QUIC.name)

    def test_picoquic_run_benchmark_one_trial(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_run_benchmark(bm, 1, Protocol.PICOQUIC.name)

    def test_picoquic_run_benchmark_multiple_trials(self):
        bm = self.setUpPicoQUICBenchmark()
        self._test_run_benchmark(bm, 5, Protocol.PICOQUIC.name)

    def _test_hosts_write_to_logs(self, bm, proxy: bool):
        self.run_benchmark(bm, 1)
        self.stopNetwork()  # Give background processes a chance to flush
        with open(f'{self.logdir}/{CLIENT_LOGFILE}', 'r') as f:
            self.assertNotEqual(f.read(), '', 'client writes to logfile')
        with open(f'{self.logdir}/{SERVER_LOGFILE}', 'r') as f:
            self.assertNotEqual(f.read(), '', 'server writes to logfile')
        router_logfile = f'{self.logdir}/{ROUTER_LOGFILE}'
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
