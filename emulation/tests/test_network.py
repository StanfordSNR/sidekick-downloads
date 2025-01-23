import unittest
from network import *


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
