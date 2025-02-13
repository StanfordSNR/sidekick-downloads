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


class TestFileDownloadBenchmarks(CLITestCase):
    def parse_json_lines(self, output):
        lines = []
        for line in output.split('\n'):
            try:
                line = json.loads(line)
                lines.append(line)
            except json.decoder.JSONDecodeError:
                continue
        return lines

    def _test_file_download_benchmark(
        self,
        protocol,
        network_options: List[str]=[],
        protocol_options: List[str]=[],
    ):
        stdout, _ = self.execute_command(
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

    @unittest.skip('skip chromium tests')
    def test_google_quic_benchmark_default(self):
        self._test_file_download_benchmark('quic')

    @unittest.skip('skip chromium tests')
    def test_google_quic_benchmark_with_proxy(self):
        self._test_file_download_benchmark('quic', ['--proxy', 'sidekick'])

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_benchmark_default(self):
        self._test_file_download_benchmark('quiche')

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_benchmark_with_proxy(self):
        self._test_file_download_benchmark('quiche', ['--proxy', 'sidekick'])

    def test_tcp_benchmark_default(self):
        self._test_file_download_benchmark('tcp')

    def test_tcp_benchmark_with_pepsal(self):
        self._test_file_download_benchmark('tcp', ['--proxy', 'pepsal'])

    def test_tcp_benchmark_with_bridge(self):
        self._test_file_download_benchmark('tcp', ['--proxy', 'bridge'])

    def test_tcp_benchmark_with_sidekick(self):
        self._test_file_download_benchmark('tcp', ['--proxy', 'sidekick'])

    def test_picoquic_benchmark_default(self):
        self._test_file_download_benchmark('picoquic')

    def test_picoquic_benchmark_with_bridge(self):
        self._test_file_download_benchmark('picoquic', ['--proxy', 'bridge'])

    def test_picoquic_benchmark_with_sidekick(self):
        self._test_file_download_benchmark('picoquic', ['--proxy', 'sidekick'])

    def test_picoquic_benchmark_with_quacker(self):
        self._test_file_download_benchmark('picoquic', ['--quacker'])

    def test_picoquic_benchmark_with_quacker_and_sidekick(self):
        self._test_file_download_benchmark('picoquic', ['--proxy', 'sidekick', '--quacker'])

    def test_picoquic_benchmark_with_ack_delay(self):
        self._test_file_download_benchmark('picoquic', protocol_options=['--ack-delay', '50'])

    def test_quacker_prints_quacks(self):
        _, stderr = self.execute_command(
            'picoquic',
            network_options=['--quacker', '--frequency', '100', '--debug'],
        )

        # Parse debug output related to the quacker for lines that describe the
        # number of packets in the sent quacks
        pattern = r'\[quack\] .* quack (\d+)'
        quacks = []
        for line in stderr.split('\n'):
            match = re.search(pattern, line)
            if not match:
                continue
            num_packets = int(match.group(1))
            quacks.append(num_packets)

        # The number of packets in each sent quack is increasing
        self.assertGreater(len(quacks), 0, 'sent at least 1 quack')
        self.assertGreaterEqual(len(quacks), 2, 'should send more at this freq')
        for i in range(len(quacks) - 1):
            self.assertLessEqual(quacks[i], quacks[i+1], quacks)

    def test_tcpdump(self):
        self.assertEqual(len(os.listdir(self.logdir)), 0)
        network_options = ['--tcpdump']
        self.execute_command('picoquic', network_options)
        entries = os.listdir(self.logdir)
        self.assertGreater(len(entries), 0, entries)
        hosts = ['h1-eth0', 'h2-eth0', 'p1-eth0', 'p1-eth1']
        for host in hosts:
            self.assertIn(f'{host}.pcap', entries, host)
        for host in hosts:
            file_size = os.path.getsize(f'{self.logdir}/{host}.pcap')
            self.assertGreater(file_size, 0, host)
