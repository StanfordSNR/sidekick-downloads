
import json
from datetime import datetime
from abc import ABC, abstractmethod
from typing import List

class BenchmarkResult(ABC):
    def __init__(self, label: str, protocol: str, proxy_type: str):
        """Initialize the data structure for tracking benchmark results over
        multiple trials.
        """
        self._inputs = {
            'label': label,
            'protocol': protocol,
            'num_trials': 0,
            'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
        data_size = self.inputs.get('data_size')
        if data_size is not None:
            self.curr_output()['throughput_mbps'] = \
                8 * data_size / 1000000 / time_s

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
                    'throughput_mbps': float,
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
        super().__init__(label, protocol, proxy_type)
        self.inputs['data_size'] = data_size
        self.inputs['cca'] = cca

    def curr_output(self) -> dict:
        """Current trial. Only one connection per trial.
        """
        assert len(self.outputs) > 0
        return self.outputs[-1]


class MediaBenchmarkResult(BenchmarkResult):
    """Tracks results over multiple trials. Each trial includes the result of
    a single media client connection.

    Schema:
        {
            'inputs': { # required
                'label': str,
                'protocol': str,
                'num_trials': int,
                'start_time': str,
                'proxy_type': str
            },
            'outputs': [
                {
                    'success': bool, # required
                    'time_s': float,
                    'statistics': {
                        'ifaces': [str],
                        'tx_packets': [int],
                        'tx_bytes': [int],
                        'rx_packets': [int],
                        'rx_bytes': [int]
                    },
                    'client_latencies': [int],
                    'server_latencies': [int],
                    'client_num_spurious': int,
                }
            ]
        }
    """

    def __init__(self, label: str, proxy_type: str):
        super().__init__(label, 'media', proxy_type)

    def curr_output(self) -> dict:
        assert len(self.outputs) > 0
        return self.outputs[-1]

    def set_client_latencies(self, client_latencies: List[int]):
        self.curr_output()['client_latencies'] = client_latencies

    def set_server_latencies(self, server_latencies: List[int]):
        self.curr_output()['server_latencies'] = server_latencies

    def set_client_num_spurious(self, num_spurious: int):
        self.curr_output()['client_num_spurious'] = num_spurious


class MulticastBenchmarkResult(BenchmarkResult):
    """Tracks results over multiple trials. Each trial includes the result of
    a multiple multicast client connections. Each entry in 'latencies' and
    'num_spurious' corresponds to the client at the same index in 'client_ids'.

    Schema:
        {
            'inputs': { # required
                'label': str,
                'protocol': str,
                'num_trials': int,
                'start_time': str,
                'proxy_type': str
            },
            'outputs': [
                {
                    'success': bool, # required
                    'time_s': float,
                    'statistics': {
                        'ifaces': [str],
                        'tx_packets': [int],
                        'tx_bytes': [int],
                        'rx_packets': [int],
                        'rx_bytes': [int]
                    },
                    'client_ids': [str],
                    'latencies': [[int]],
                    'num_spurious': [int],
                }
            ]
        }
    """

    def __init__(self, label: str, proxy_type: str):
        super().__init__(label, 'multicast', proxy_type)

    def curr_output(self) -> dict:
        assert len(self.outputs) > 0
        return self.outputs[-1]

    def set_client_ids(self, client_ids: List[str]):
        self.curr_output()['client_ids'] = client_ids

    def set_latencies(self, latencies: List[List[int]]):
        self.curr_output()['latencies'] = latencies

    def set_num_spurious(self, num_spurious: List[int]):
        self.curr_output()['num_spurious'] = num_spurious
