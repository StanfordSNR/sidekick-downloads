"""
Test benchmark/result.py.
"""
import unittest
import json
from abc import ABC, abstractmethod

from benchmark import HTTPBenchmarkResult

class TestBenchmarkResult(ABC):
    DEFAULT_TIME_S = 100
    DEFAULT_ADDL_DATA = 'additional_data'

    def setUp(self):
        # Default parameters
        self.label = 'my_label'
        self.protocol = 'TCP'
        self.data_size = 1000
        self.cca = 'cubic'
        self.proxy_type = 'pepsal'

    def appendTrial(self, res):
        '''Indicate the beginning of a new trial.
        Input: a BenchmarkResult.
        '''
        res.append_new_output()

    @abstractmethod
    def appendConnection(self, res):
        '''Indicate the beginning of a new iteration within a trial,
        if applicable.
        Input: a BenchmarkResult.
        '''
        pass

    @abstractmethod
    def completeTrial(self, res):
        '''Indicate the end of a trial.
        Input: a BenchmarkResult.
        '''
        pass

    @abstractmethod
    def connectionOutput(self, res_json: dict, n_trial: int, n_conn: int) -> dict:
        '''Get the output from the `n_conn`'th iteration of the `n_trial`'th trial.
        If each trial consists of one connection, then `n_conn` is ignored and
        this is the same as `trialOutput`.
        Input: a BenchmarkResult as a json-formatted string, the index of the
               trial, and the index of the connection within the trial.
        Output: a json-formatted string for a single connection
                according to the BenchmarkResult schema.
        '''
        pass

    @abstractmethod
    def trialOutput(self, res_json: dict, n: int) -> dict:
        '''Get the output from the nth trial.
        Input: a BenchmarkResult as a json-formatted string and the
               index of the trial.
        Output: a json-formatted string for a single trial
                according to the BenchmarkResult schema.
        '''
        pass

    def _test_initialize_result(self, res):
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

    def _test_append_one_output(self, res):
        # Append one output
        self.appendTrial(res)
        self.completeTrial(res)
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 1)
        self.assertEqual(len(x['outputs']), 1)
        trial = self.trialOutput(x, 0)
        self.assertFalse(trial.get('success'))

        # Set keys of new output
        self.appendConnection(res)
        time_s = 100
        additional_data = 'additional_data'
        res.set_success(True)
        res.set_timeout(False)
        res.set_time_s(time_s)
        res.set_network_statistics({})
        res.set_additional_data(additional_data)
        self.completeTrial(res)

        # Check keys of new output
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 1)
        self.assertEqual(len(x['outputs']), 1)
        output = self.trialOutput(x, 0)
        self.assertTrue(output.get('success'))
        output = self.connectionOutput(x, 0, 0)
        self.assertTrue(output.get('success'))
        self.assertFalse(output.get('timeout'))
        self.assertEqual(output.get('time_s'), time_s)
        self.assertIsInstance(output.get('statistics'), dict)
        self.assertEqual(output.get('additional_data'), additional_data)

    def _test_append_multiple_outputs(self, res):

        # Append multiple trials
        self.appendTrial(res)
        self.appendConnection(res)
        res.set_success(True)
        res.set_additional_data('x')
        self.completeTrial(res)

        self.appendTrial(res)
        self.appendConnection(res)
        res.set_additional_data('y')
        self.completeTrial(res)

        self.appendTrial(res)
        self.appendConnection(res)
        res.set_success(True)
        res.set_additional_data('z')
        self.completeTrial(res)

        # Check json
        x = json.loads(res.json())
        self.assertEqual(x['inputs'].get('num_trials'), 3)
        outputs = x['outputs']
        self.assertEqual(len(outputs), 3)
        self.assertTrue(self.trialOutput(x, 0).get('success'))
        self.assertFalse(self.trialOutput(x, 1).get('success'))
        self.assertTrue(self.trialOutput(x, 2).get('success'))

        self.assertEqual(self.connectionOutput(x, 0, 0).get('additional_data'), 'x')
        self.assertEqual(self.connectionOutput(x, 1, 0).get('additional_data'), 'y')
        self.assertEqual(self.connectionOutput(x, 2, 0).get('additional_data'), 'z')

    def _test_additional_data(self, res):
        def data(res):
            res_json = json.loads(res.json())
            connection = self.connectionOutput(res_json, -1, -1)
            return connection.get('additional_data')

        # without merge
        self.appendTrial(res)
        self.appendConnection(res)
        self.assertIsNone(data(res))
        res.set_additional_data({'a': 1}, merge=False)
        self.assertEqual(data(res), {'a': 1})
        res.set_additional_data({'b': 2}, merge=False)
        self.assertEqual(data(res), {'b': 2})
        self.completeTrial(res)

        # with merge
        self.appendTrial(res)
        self.appendConnection(res)
        self.assertIsNone(data(res))
        res.set_additional_data({'a': 1}, merge=True)
        self.assertEqual(data(res), {'a': 1})
        res.set_additional_data({'b': 2}, merge=True)
        self.assertEqual(data(res), {'a': 1, 'b': 2})
        res.set_additional_data({'a': 3}, merge=True)
        self.assertEqual(data(res), {'a': 3, 'b': 2}, 'merge with conflict')
        res.set_additional_data({'c': 3})
        self.assertEqual(data(res), {'c': 3}, 'default is to not merge')
        self.completeTrial(res)



class TestHTTPBenchmarkResult(TestBenchmarkResult, unittest.TestCase):

    def appendConnection(self, res):
        # No-op
        return

    def completeTrial(self, res):
        # No-op
        return

    def connectionOutput(self, res_json: str, n_trial: int, n_conn: int) -> str:
        return res_json['outputs'][n_trial]

    def trialOutput(self, res_json: str, n: int) -> str:
        return res_json['outputs'][n]

    def test_initialize_result(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                            self.cca, self.proxy_type)
        super()._test_initialize_result(res)

    def test_append_one_output(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                                  self.cca, self.proxy_type)
        super()._test_append_one_output(res)

    def test_append_multiple_outputs(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                                  self.cca, self.proxy_type)
        super()._test_append_multiple_outputs(res)

    def test_additional_data(self):
        res = HTTPBenchmarkResult(self.label, self.protocol, self.data_size,
                                  self.cca, self.proxy_type)
        super()._test_additional_data(res)
