"""
Test the CLI entrypoint into the program in main.py.
"""
import unittest
import subprocess
import os
import json
import re

from typing import List, Tuple


class TestFileDownloadBenchmarks(unittest.TestCase):
    def setUp(self):
        # Run tests from the upper-level directory (the sidekick home)
        self._cwd = os.getcwd()
        os.chdir('..')

    def tearDown(self):
        os.chdir(self._cwd)

    def execute_command(
        self,
        protocol,
        network_options: List[str]=[],
        protocol_options: List[str]=[],
    ) -> Tuple[str, str]:
        cmd = ['python3', 'emulation/main.py']
        cmd += network_options
        cmd += [protocol]
        cmd += protocol_options
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, result.stderr

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

    def test_tcp_benchmark(self):
        self._test_file_download_benchmark('tcp')
        self._test_file_download_benchmark('tcp', ['--sidekick'])
        self._test_file_download_benchmark('tcp', protocol_options=['--pep'])

    @unittest.skip('skip chromium tests')
    def test_google_quic_benchmark(self):
        self._test_file_download_benchmark('quic')
        self._test_file_download_benchmark('quic', ['--sidekick'])

    @unittest.skip('skip cloudflare tests')
    def test_cloudflare_quic_benchmark(self):
        self._test_file_download_benchmark('quiche')
        self._test_file_download_benchmark('quiche', ['--sidekick'])

    def test_picoquic_benchmark(self):
        self._test_file_download_benchmark('picoquic')
        self._test_file_download_benchmark('picoquic', ['--sidekick'])
        self._test_file_download_benchmark('picoquic', ['--quacker'])
        self._test_file_download_benchmark('picoquic', ['--quacker', '--sidekick'])

    def test_quacker_prints_quacks(self):
        _, stderr = self.execute_command(
            'picoquic',
            network_options=['--quacker', '--frequency', '100'],
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
