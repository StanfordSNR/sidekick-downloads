"""
Test the CLI entrypoint into the program in main.py.
"""
import unittest
import subprocess
import os
import json
import re
import sys
import tempfile

from typing import List, Tuple
from unittest.mock import patch

from network import EmulatedNetwork
from main import parse_args, main
from common import *


class CLITestCase(unittest.TestCase):
    def setUp(self):
        # Run tests from the upper-level directory (the sidekick home)
        self._cwd = os.getcwd()
        os.chdir('..')

        # Set up logging directory
        self._logdir = tempfile.TemporaryDirectory()
        self.logdir = self._logdir.name

    def tearDown(self):
        self._logdir.cleanup()
        os.chdir(self._cwd)

    def execute_command(
        self,
        protocol,
        network_options: List[str]=[],
        protocol_options: List[str]=[],
    ) -> Tuple[str, str]:
        cmd = ['python3', 'emulation/main.py']
        cmd += ['--logdir', self.logdir]
        cmd += network_options
        cmd += [protocol]
        cmd += protocol_options
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, result.stderr

    def execute_main_func(
        self,
        protocol,
        network_options: List[str]=[],
        protocol_options: List[str]=[],
    ):
        argv = []
        argv += ['--logdir', self.logdir]
        argv += network_options
        argv += [protocol]
        argv += protocol_options
        main(parse_args(argv))

    def parse_json_lines(self, output):
        lines = []
        for line in output.split('\n'):
            try:
                line = json.loads(line)
                lines.append(line)
            except json.decoder.JSONDecodeError:
                continue
        return lines

    def parse_quacks(self, lines: List[str]) -> List[int]:
        quacks = []
        pattern = r'DEBUG .* quack (\d+)'
        for line in lines:
            match = re.search(pattern, line)
            if not match:
                continue
            num_packets = int(match.group(1))
            quacks.append(num_packets)
        return quacks

    def read_logfile(self, filename: str, lines: bool=True):
        with open(f'{self.logdir}/{filename}', 'r') as f:
            if lines:
                return f.readlines()
            else:
                return f.read()

    def execute_command_and_check(
        self,
        protocol,
        network_options: List[str]=[],
        protocol_options: List[str]=[],
    ):
        stdout, stderr = self.execute_command(
            protocol, network_options, protocol_options)
        self.assertNotEqual(stdout, '', 'results are logged to stdout')
        lines = self.parse_json_lines(stdout)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn('inputs', line)
        self.assertIn('outputs', line)
        outputs = line['outputs']
        self.assertEqual(len(outputs), 1)
        self.assertTrue(outputs[0].get('success'))
        return (stdout, stderr)


class TestCommandLineOptions(CLITestCase):
    def setUp(self):
        super().setUp()
        # Suppress logging
        self._stderr = sys.stderr
        self._stdout = sys.stdout
        sys.stderr = open(os.devnull, 'w')
        sys.stdout = open(os.devnull, 'w')

    @unittest.skip('command line tests interfering with others for some reason')
    @patch.object(EmulatedNetwork, 'start_tcp_pep')
    def test_start_tcp_pep(self, mock_start_tcp_pep):
        mock_start_tcp_pep.assert_not_called()
        self.execute_main_func('tcp', ['--proxy', 'pepsal'])
        mock_start_tcp_pep.assert_called_once()

    @patch('main.benchmark_tcp')
    @patch('main.benchmark_picoquic')
    @patch.object(EmulatedNetwork, 'start_bridge')
    @unittest.skip('command line tests interfering with others for some reason')
    def test_start_bridge(
        self, mock_start_bridge, mock_benchmark_tcp, mock_benchmark_picoquic,
    ):
        mock_start_bridge.assert_not_called()
        self.execute_main_func('tcp')
        mock_start_bridge.assert_not_called()
        self.execute_main_func('tcp', ['--proxy', 'bridge'])
        mock_start_bridge.assert_called_once()
        self.execute_main_func('picoquic', ['--proxy', 'bridge'])
        self.assertEqual(mock_start_bridge.call_count, 2)

    @patch('main.benchmark_tcp')
    @patch('main.benchmark_picoquic')
    @patch.object(EmulatedNetwork, 'start_sidekick')
    @unittest.skip('command line tests interfering with others for some reason')
    def test_start_sidekick(
        self, mock_start_sidekick, mock_benchmark_tcp, mock_benchmark_picoquic,
    ):
        mock_start_sidekick.assert_not_called()
        self.execute_main_func('tcp')
        mock_start_sidekick.assert_not_called()
        self.execute_main_func('tcp', ['--proxy', 'sidekick'])
        mock_start_sidekick.assert_called_once()
        self.execute_main_func('picoquic', ['--proxy', 'sidekick'])
        self.assertEqual(mock_start_sidekick.call_count, 2)

    @patch.object(EmulatedNetwork, 'start_client_quacker')
    @unittest.skip('command line tests interfering with others for some reason')
    def test_start_client_quacker(self, mock_start_client_quacker):
        mock_start_client_quacker.assert_not_called()
        self.execute_main_func('picoquic')
        mock_start_client_quacker.assert_not_called()
        self.execute_main_func('picoquic', ['--quacker'])
        mock_start_client_quacker.assert_called_once()
        self.execute_main_func('picoquic', ['--quacker', '--proxy', 'sidekick'])
        self.assertEqual(mock_start_client_quacker.call_count, 2)


class TestNetworkOptions(CLITestCase):
    @unittest.skip('skip chromium tests')
    def test_google_quic_benchmark_default(self):
        self.execute_command_and_check('quic')

    @unittest.skip('skip chromium tests')
    def test_google_quic_benchmark_with_proxy(self):
        self.execute_command_and_check('quic', ['--proxy', 'sidekick'])

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_benchmark_default(self):
        self.execute_command_and_check('quiche')

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_benchmark_with_proxy(self):
        self.execute_command_and_check('quiche', ['--proxy', 'sidekick'])

    def test_tcp_benchmark_default(self):
        self.execute_command_and_check('tcp')

    def test_tcp_benchmark_with_pepsal(self):
        self.execute_command_and_check('tcp', ['--proxy', 'pepsal'])
        output = self.read_logfile(ROUTER_LOGFILE, lines=False)
        self.assertIn('Saving new SYN', output)

    def test_tcp_benchmark_with_bridge(self):
        self.execute_command_and_check('tcp', ['--proxy', 'bridge'])

    def test_tcp_benchmark_with_sidekick(self):
        self.execute_command_and_check('tcp', ['--proxy', 'sidekick'])

    def test_udp_benchmark_with_bridge(self):
        self.execute_command_and_check('picoquic', ['--proxy', 'bridge'])

    def test_udp_benchmark_with_sidekick(self):
        self.execute_command_and_check('picoquic', ['--proxy', 'sidekick'])

    def test_tcpdump(self):
        self.assertEqual(len(os.listdir(self.logdir)), 0)
        network_options = ['--tcpdump']
        self.execute_command_and_check('picoquic', network_options)
        entries = os.listdir(self.logdir)
        self.assertGreater(len(entries), 0, entries)
        hosts = ['h1-eth0', 'h2-eth0', 'p1-eth0', 'p1-eth1']
        for host in hosts:
            self.assertIn(f'{host}.pcap', entries, host)
        for host in hosts:
            file_size = os.path.getsize(f'{self.logdir}/{host}.pcap')
            self.assertGreater(file_size, 0, host)

    def test_perf(self):
        self.assertEqual(len(os.listdir(self.logdir)), 0)
        network_options = ['--perf', '--proxy', 'pepsal']
        self.execute_command_and_check('tcp', network_options)
        entries = os.listdir(self.logdir)
        self.assertGreater(len(entries), 0, entries)
        logfiles = [CLIENT_LOGFILE, SERVER_LOGFILE, ROUTER_LOGFILE]
        for logfile in logfiles:
            self.assertIn(f'{logfile}.perf', entries, logfile)
        for logfile in logfiles:
            file_size = os.path.getsize(f'{self.logdir}/{logfile}.perf')
            self.assertGreater(file_size, 0, logfile)


class TestPicoquicBenchmark(CLITestCase):
    def test_picoquic_benchmark_simple(self):
        self.execute_command_and_check('picoquic')

    def test_picoquic_benchmark_with_sidekick(self):
        self.execute_command_and_check('picoquic', ['--proxy', 'sidekick'])

    def test_picoquic_benchmark_with_ack_delay(self):
        self.execute_command_and_check('picoquic', protocol_options=['--ack-delay', '50'])

    def test_picoquic_client_does_not_quack_by_default(self):
        self.execute_command_and_check('picoquic', ['--debug', '--proxy', 'sidekick'])
        lines = self.read_logfile(ROUTER_LOGFILE)
        quacks = self.parse_quacks(lines)
        self.assertEqual(quacks, [], 'no quacks are received')


class TestMediaBenchmark(CLITestCase):
    def test_media_benchmark_simple(self):
        self.execute_command_and_check('media')

    def test_media_benchmark_with_sidekick(self):
        network_options = [
            '--proxy', 'sidekick', '--quacker', '--threshold', '8',
        ]
        self.execute_command_and_check('media', network_options)


class TestSidekickProtocolBasic(CLITestCase):
    def _test_discovery(self):
        # Proxy receives discovery packet from client
        pattern = 'Received discovery packet from client'
        self.assertIn(pattern, self.read_logfile(ROUTER_LOGFILE, lines=False))

        # Client quacks only after receiving discover ack
        received_discover_ack = False
        quacked_after_discover_ack = False
        lines = self.read_logfile(CLIENT_LOGFILE)
        for line in lines:
            if 'Received DiscoverACK from proxy' in line:
                received_discover_ack = True
            if re.search(r'DEBUG .* quack (\d+)', line):
                self.assertTrue(received_discover_ack, 'client quacked before receiving a discover ACK')
                quacked_after_discover_ack = True
                break
        self.assertTrue(received_discover_ack, lines)
        self.assertTrue(quacked_after_discover_ack, lines)

    def _test_quacker_sends_quacks(self):
        # Parse debug output related to the quacker for lines that describe
        # the number of packets in the sent quacks
        lines = self.read_logfile(CLIENT_LOGFILE)
        quacks = self.parse_quacks(lines)

        # The number of packets in each sent quack is increasing
        self.assertGreater(len(quacks), 0, 'sent at least 1 quack')
        self.assertGreaterEqual(len(quacks), 2, 'should send more at this freq')
        for i in range(len(quacks) - 1):
            self.assertLessEqual(quacks[i], quacks[i+1], quacks)

    def _test_sidekick_receives_quacks(self):
        # Parse router logfile for number of packets in the received quACKs
        lines = self.read_logfile(ROUTER_LOGFILE)
        quacks = self.parse_quacks(lines)

        # The number of packets in each received quack is increasing
        self.assertGreater(len(quacks), 0, 'received at least 1 quack')
        self.assertGreaterEqual(len(quacks), 2, 'should receive more at this freq')
        for i in range(len(quacks) - 1):
            self.assertLessEqual(quacks[i], quacks[i+1], quacks)

    def execute_sidekick_command_and_check(
        self, protocol, add_network_options=[], add_protocol_options=[],
    ):
        self.execute_command_and_check(
            protocol,
            ['--debug', '--proxy', 'sidekick'] + add_network_options,
            add_protocol_options,
        )
        self._test_discovery()
        self._test_quacker_sends_quacks()
        self._test_sidekick_receives_quacks()

    def test_sniffing_quacker_default(self):
        self.execute_sidekick_command_and_check(
            'picoquic', add_network_options=['--quacker'])
        self.execute_sidekick_command_and_check(
            'media', add_network_options=['--quacker'])

    def test_picoquic_client_quacker_default(self):
        self.execute_sidekick_command_and_check(
            'picoquic',
            add_protocol_options=['--client-quacker'],
        )

    def test_media_client_quacker_default(self):
        self.execute_sidekick_command_and_check(
            'media',
            add_protocol_options=['--client-quacker'],
        )

    def test_sniffing_picoquic_quacker_different_frequencies(self):
        def test(freq_ms, freq_pkts):
            add_network_options = ['--quacker']
            add_network_options += ['--freq-ms', str(freq_ms)]
            add_network_options += ['--freq-pkts', str(freq_pkts)]
            self.execute_sidekick_command_and_check('picoquic', add_network_options)
        test(100, 0)
        test(0, 8)
        test(50, 20)

    def test_sniffing_media_quacker_different_frequencies(self):
        def test(freq_ms, freq_pkts, freq_media_ms):
            add_network_options = ['--quacker']
            add_network_options += ['--freq-ms', str(freq_ms)]
            add_network_options += ['--freq-pkts', str(freq_pkts)]
            add_protocol_options = ['--frequency', str(freq_media_ms)]
            self.execute_sidekick_command_and_check(
                'media', add_network_options, add_protocol_options,
            )
        test(100, 0, 20)
        test(0, 8, 10)
        test(50, 20, 20)

    def test_picoquic_client_quacker_different_frequencies(self):
        def test(freq_ms, freq_pkts):
            add_network_options = ['--freq-ms', str(freq_ms)]
            add_network_options += ['--freq-pkts', str(freq_pkts)]
            self.execute_sidekick_command_and_check(
                'picoquic', add_network_options, ['--client-quacker'],
            )
        test(100, 0)
        test(0, 8)
        test(50, 20)

    def test_media_client_quacker_different_frequencies(self):
        def test(freq_ms, freq_pkts, freq_media_ms):
            add_network_options = ['--freq-ms', str(freq_ms), '--freq-pkts', str(freq_pkts)]
            add_protocol_options = ['--client-quacker', '--frequency', str(freq_media_ms)]
            self.execute_sidekick_command_and_check(
                'media', add_network_options, add_protocol_options,
            )
        test(100, 0, 20)
        test(0, 8, 10)
        test(50, 20, 20)

    def test_sniffing_quacker_different_threshold(self):
        self.execute_sidekick_command_and_check(
            'picoquic', ['--quacker', '--threshold', '8'])
        self.execute_sidekick_command_and_check(
            'media', ['--quacker', '--threshold', '8'])

    def test_sniffing_quacker_different_port(self):
        self.execute_sidekick_command_and_check(
            'picoquic', ['--quacker', '--quackee-port', '5250'])
        self.execute_sidekick_command_and_check(
            'media', ['--quacker', '--quackee-port', '5250'])

    def test_picoquic_client_quacker_different_threshold(self):
        self.execute_sidekick_command_and_check(
            'picoquic', ['--threshold', '8'], ['--client-quacker'])

    def test_picoquic_client_quacker_different_port(self):
        self.execute_sidekick_command_and_check(
            'picoquic', ['--quackee-port', '5250'], ['--client-quacker'])

    def test_media_client_quacker_different_threshold(self):
        self.execute_sidekick_command_and_check(
            'media', ['--threshold', '8'], ['--client-quacker'])

    def test_media_client_quacker_different_port(self):
        self.execute_sidekick_command_and_check(
            'media', ['--quackee-port', '5250'], ['--client-quacker'])


class TestSidekickProtocolReset(CLITestCase):
    def _test_quacker_receives_resets(self):
        self.assertIn('ExceededThreshold', self.read_logfile(ROUTER_LOGFILE, lines=False))
        self.assertIn('Received Reset', self.read_logfile(CLIENT_LOGFILE, lines=False))

    def test_sniffing_picoquic_quacker_receives_resets(self):
        self.execute_command(
            'picoquic',
            network_options=['--quacker', '--proxy', 'sidekick', '--threshold', '1', '--loss1', '10'],
        )
        self._test_quacker_receives_resets()

    def test_sniffing_media_quacker_receives_resets(self):
        self.execute_command(
            'media',
            network_options=[
                '--quacker', '--proxy', 'sidekick', '--loss1', '10',
                '--threshold', '1', '--freq-ms', '0', '--freq-pkts', '50',
            ],
            protocol_options=['--frequency', '1'],
        )
        self._test_quacker_receives_resets()

    def test_picoquic_client_quacker_receives_resets(self):
        self.execute_command(
            'picoquic',
            network_options=['--proxy', 'sidekick', '--threshold', '1', '--loss1', '10'],
            protocol_options=['--client-quacker'],
        )
        self._test_quacker_receives_resets()

    def test_media_client_quacker_receives_resets(self):
        self.execute_command(
            'media',
            network_options=[
                '--proxy', 'sidekick', '--loss1', '10',
                '--threshold', '1', '--freq-ms', '0', '--freq-pkts', '50',
            ],
            protocol_options=['--frequency', '1', '--client-quacker'],
        )
        self._test_quacker_receives_resets()
