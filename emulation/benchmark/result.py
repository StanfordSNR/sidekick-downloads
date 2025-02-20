import json
from datetime import datetime
from abc import ABC, abstractmethod

class BenchmarkResult(ABC):
    def __init__(self, label: str, protocol: str, data_size: int, cca: str,
                 proxy_type: str):
        """Initialize the data structure for tracking benchmark results over
        multiple trials.
        """
        self._inputs = {
            'label': label,
            'protocol': protocol,
            'num_trials': 0,
            'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'data_size': data_size,
            'cca': cca,
            'proxy_type': proxy_type,
        }
        self._outputs = []

    @property
    def outputs(self):
        return self._outputs

    @property
    def inputs(self):
        return self._inputs

    def append_new_output(self):
        """A new trial is complete. Append an output so following "set_*"
        functions set the metrics for this recently completed trial.
        """
        self._inputs['num_trials'] += 1
        self._outputs.append({
            'success': False,
        })

    def set_success(self, success: bool):
        """Set whether most recent iteration in most recent trial was successful.
        """
        self.curr_output()['success'] = success

    def set_timeout(self, timeout: bool):
        """Set whether an unsuccessful iteration was due to a timeout.
        """
        self.curr_output()['timeout'] = timeout

    def set_time_s(self, time_s: float):
        """Set the request latency for the most recent iteration.
        """
        self.curr_output()['time_s'] = time_s
        self.curr_output()['throughput_mbps'] = \
            8 * self.inputs['data_size'] / 1000000 / time_s

    def set_network_statistics(self, statistics: dict):
        """Set the network statistics for the most recent iteration.
        """
        self.curr_output()['statistics'] = statistics

    def set_additional_data(self, data, merge=False):
        """Set additional data for the most recent iteration.
        """
        data_init = self.curr_output().get('additional_data')
        if (data_init is None) or not merge:
            self.curr_output()['additional_data'] = data
        else:
            assert isinstance(data_init, dict)
            assert isinstance(data, dict)
            for k, v in data.items():
                data_init[k] = v

    def json(self, prettify=False) -> str:
        """Format the current result as a JSON string.
        The length of `outputs` is equal to `num_trials`.
        The `success` field is required for each output, and all other
        fields are optional. The `EmulatedNetwork.snapshot_statistics()`
        function defines the schema of `network_statistics`.
        """
        result = {
            'inputs': self._inputs,
            'outputs': self._outputs,
        }
        if prettify:
            return json.dumps(result, indent=2)
        else:
            return json.dumps(result)

    @abstractmethod
    def curr_output(self) -> dict:
        """Return output data for the most recent iteration of the
        most recent trial. This is what the "set_*" functions will modify.
        """
        pass


class HTTPBenchmarkResult(BenchmarkResult):
    """Tracks results over multiple trials. Each trial includes the result of
    a single HTTP request/response. Stored data is summary, not timeseries.

    Schema:
        {
            'inputs': { # required
                'label': str,
                'protocol': str,
                'num_trials': int,
                'start_time': str,
                'data_size': int,
                'cca': str,
                'proxy_type': str
            },
            'outputs': [
                {
                    'success': bool, # required
                    'timeout': bool,
                    'time_s': float,
                    'statistics': {
                        'ifaces': [str],
                        'tx_packets': [int],
                        'tx_bytes': [int],
                        'rx_packets': [int],
                        'rx_bytes': [int]
                    }
                    'additional_data': any
                }
            ]
        }
    """

    def __init__(self, label: str, protocol: str, data_size: int, cca: str,
                 proxy_type: str):
        super().__init__(label, protocol, data_size, cca, proxy_type)

    def curr_output(self) -> dict:
        """Current trial. Only one connection per trial.
        """
        assert len(self.outputs) > 0
        return self.outputs[-1]

class HTTPConcurrentBenchmarkResult(BenchmarkResult):
    """Tracks results over multiple trials. Each trial includes the result of
    multiple concurrent HTTP requests/responses. Stored data is summary and as
    a timeseries.

    Schema:
        {
            'inputs': { # required
                'label': str,
                'protocol': str,
                'num_trials': int,
                'start_time': str,
                'data_size': int,
                'cca': str,
                'proxy_type': str,
                'connections': int
            },
            'outputs': [
                'success': bool, # required
                'connections': [
                    {
                        'success': bool, # required
                        'timeout': bool,
                        'time_s': float,
                        'statistics': {
                            'ifaces': [str],
                            'tx_packets': [int],
                            'tx_bytes': [int],
                            'rx_packets': [int],
                            'rx_bytes': [int]
                        }
                        'additional_data': any
                    },
                    // ...
                ]
            ]
        }
    """
    def __init__(self, label: str, protocol: str, data_size: int, cca: str,
                 proxy_type: str, n_conns: int):
        super().__init__(label, protocol, data_size, cca, proxy_type)
        self.inputs['n_connections'] = n_conns

    def curr_output(self) -> dict:
        """Current connection in current trial.
        """
        assert len(self.outputs) > 0
        assert len(self.outputs[-1]) > 0
        return self.outputs[-1]['connections'][-1]

    def append_new_connection(self):
        """Add a new connection to the current trial.
        """
        self.curr_trial()['connections'].append({
            'success': False,
        })

    def curr_trial(self) -> dict:
        """Overarching struct for current trial.
        Multiple connections per trial.
        """
        return self.outputs[-1]

    def trial_complete(self):
        """Indicate that all connections have been added to the current trial.
        Set trial success iff all connections in the trial succeeded.
        """
        assert len(self.curr_trial()['connections']) == self.inputs['n_connections']
        self.curr_trial()['success'] = all(conn['success'] for conn in self.curr_trial()['connections'])

