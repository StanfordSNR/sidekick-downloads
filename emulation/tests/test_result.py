"""
Test benchmark/result.py.
"""
import unittest
import json

from benchmark import HTTPBenchmarkResult


class TestHTTPBenchmarkResult(unittest.TestCase):
    def setUp(self):
        # Default parameters
        self.label = 'my_label'
        self.protocol = 'TCP'
        self.data_size = 1000
        self.cca = 'cubic'
        self.proxy_type = 'pepsal'

    def test_initialize_result(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                                  self.cca, self.proxy_type)
        x = res.json()
        self.assertIsInstance(x, str)

        # Check schema
        x = json.loads(x)
        self.assertIn('inputs', x)
        self.assertIn('outputs', x)

        # Check inputs
        inputs = x['inputs']
        self.assertEqual(inputs.get('label'), self.label)
        self.assertEqual(inputs.get('protocol'), self.protocol)
        self.assertEqual(inputs.get('data_size'), self.data_size)
        self.assertEqual(inputs.get('cca'), self.cca)
        self.assertEqual(inputs.get('proxy_type'), self.proxy_type)
        self.assertIsInstance(inputs.get('start_time'), str)
        self.assertEqual(inputs.get('num_trials'), 0)

        # Check outputs
        self.assertEqual(x['outputs'], [])

    def test_append_one_output(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                                  self.cca, self.proxy_type)

        # Check baseline
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 0)
        self.assertEqual(len(x['outputs']), 0)

        # Append one output
        res.append_new_output()
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 1)
        self.assertEqual(len(x['outputs']), 1)
        self.assertFalse(x['outputs'][0].get('success'))

        # Set keys of new output
        time_s = 100
        additional_data = 'additional_data'
        res.set_success(True)
        res.set_timeout(False)
        res.set_time_s(time_s)
        res.set_network_statistics({})
        res.set_additional_data(additional_data)
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 1)
        self.assertEqual(len(x['outputs']), 1)
        output = x['outputs'][0]
        self.assertTrue(output.get('success'))
        self.assertFalse(output.get('timeout'))
        self.assertEqual(output.get('time_s'), time_s)
        self.assertIsInstance(output.get('statistics'), dict)
        self.assertEqual(output.get('additional_data'), additional_data)

    def test_append_multiple_outputs(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                                  self.cca, self.proxy_type)

        # Check baseline
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 0)
        self.assertEqual(len(x['outputs']), 0)

        # Append multiple outputs
        res.append_new_output()
        res.set_success(True)
        res.set_additional_data('x')
        res.append_new_output()
        res.set_additional_data('y')
        res.append_new_output()
        res.set_success(True)
        res.set_additional_data('z')

        # Check json
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 3)
        outputs = x['outputs']
        self.assertEqual(len(outputs), 3)
        self.assertTrue(outputs[0].get('success'))
        self.assertFalse(outputs[1].get('success'))
        self.assertTrue(outputs[2].get('success'))
        self.assertEqual(outputs[0].get('additional_data'), 'x')
        self.assertEqual(outputs[1].get('additional_data'), 'y')
        self.assertEqual(outputs[2].get('additional_data'), 'z')
