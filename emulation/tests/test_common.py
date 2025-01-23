import unittest
import subprocess
from common import *


class TestSubprocessHandling(unittest.TestCase):
	def test_reads_all_subprocess_output(self):
		n = 10
		cmd = ['seq', str(n)]
		p = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE,
			stderr=subprocess.PIPE)
		output = []
		for line, _ in read_subprocess_pipe(p):
			output.append(line.strip())
		self.assertEqual(len(output), n, output)
		self.assertEqual(p.wait(), 0)
