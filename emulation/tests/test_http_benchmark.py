import sys
import os

import unittest

from network import OneHopNetwork
from benchmark import *


class HTTPDownloadTestCase(unittest.TestCase):
    def setUp(self):
        # Suppress stderr logging from network setup
        self._stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')

        # Setup a mininet network
        self.net = self.setUpOneHopNetwork()

        # Set default parameters
        self.data_size = 1000
        self.cca = 'cubic'
        self.certfile = 'deps/certs/out/leaf_cert.pem'
        self.keyfile = 'deps/certs/out/leaf_cert.key'

    def tearDown(self):
        self.net.stop()

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
