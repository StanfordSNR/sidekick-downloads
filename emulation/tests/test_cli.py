"""
Test the CLI entrypoint into the program in main.py.
"""
import unittest
import subprocess
import os
import json


class TestFileDownloadBenchmarks(unittest.TestCase):
    def setUp(self):
        # Run tests from the upper-level directory (the sidekick home)
        self._cwd = os.getcwd()
        os.chdir('..')

    def tearDown(self):
        os.chdir(self._cwd)

    def parse_json_lines(self, output):
        lines = []
        for line in output.split('\n'):
            try:
                line = json.loads(line)
                lines.append(line)
            except json.decoder.JSONDecodeError:
                continue
        return lines

    def _test_file_download_benchmark(self, protocol):
        result = subprocess.run(
            ['python3', 'emulation/main.py', protocol],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(result.stdout, '', 'results are logged to stdout')
        lines = self.parse_json_lines(result.stdout)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertIn('inputs', line)
        self.assertIn('outputs', line)
        outputs = line['outputs']
        self.assertEqual(len(outputs), 1)
        self.assertTrue(outputs[0].get('success'))

    def test_tcp_benchmark(self):
        self._test_file_download_benchmark('tcp')

    def test_google_quic_benchmark(self):
        self._test_file_download_benchmark('quic')

    def test_cloudflare_quic_benchmark(self):
        self._test_file_download_benchmark('quiche')

    def test_picoquic_benchmark(self):
        self._test_file_download_benchmark('picoquic')
