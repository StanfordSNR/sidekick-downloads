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

        # Set default parameters
        self.data_size = 1000
        self.cca = 'cubic'
        self.certfile = 'deps/certs/out/leaf_cert.pem'
        self.keyfile = 'deps/certs/out/leaf_cert.key'

        # Setup logfiles
        self._logdir = tempfile.TemporaryDirectory()
        self.logdir = self._logdir.name

    def tearDown(self):
        self._logdir.cleanup()
        self.net.stop()
        os.chdir(self._cwd)

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
