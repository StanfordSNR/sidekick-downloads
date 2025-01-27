import json
from datetime import datetime


class HTTPBenchmarkResult:
    def __init__(self, label: str, protocol: str, data_size: int, cca: str,
                 pep: bool):
        """Initialize the data structure for tracking benchmark results over
        multiple trials.
        """
        self.inputs = {
            'label': label,
            'protocol': protocol,
            'num_trials': 0,
            'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'data_size': data_size,
            'cca': cca,
            'pep': pep,
        }
        self.outputs = []

    def append_new_output(self):
        """A new trial is complete. Append an output so following "set_*"
        functions set the metrics for this recently completed trial.
        """
        self.inputs['num_trials'] += 1
        self.outputs.append({
            'success': False,
        })

    def set_success(self, success: bool):
        """Set whether the most recent trial was successful.
        """
        self.outputs[-1]['success'] = success

    def set_timeout(self, timeout: bool):
        """Set whether an unsuccessful trial was due to a timeout.
        """
        self.outputs[-1]['timeout'] = timeout

    def set_time_s(self, time_s: float):
        """Set the request latency.
        """
        self.outputs[-1]['time_s'] = time_s
        self.outputs[-1]['throughput_mbps'] = \
            8 * self.inputs['data_size'] / 1000000 / time_s

    def set_network_statistics(self, statistics: dict):
        """Set the network statistics as defined in `snapshot_statistics()`.
        """
        self.outputs[-1]['statistics'] = statistics

    def set_additional_data(self, data):
        """Set any additional data for the most recent trial.
        """
        self.outputs[-1]['additional_data'] = data

    def json(self, prettify=False) -> str:
        """Format the current result as a JSON string.

        {
            'inputs': {
                'label': str,
                'protocol': str,
                'num_trials': int,
                'start_time': str,
                'data_size': int,
                'cca': str,
                'pep': bool
            },
            'outputs': [
                {
                    'success': bool,
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

        The length of `outputs` is equal to `num_trials`. The `success` field
        is required for each output, and all other fields are optional. The
        `EmulatedNetwork.snapshot_statistics()` function defines the schema of
        `network_statistics`.
        """
        result = {
            'inputs': self.inputs,
            'outputs': self.outputs,
        }
        if prettify:
            return json.dumps(result, indent=2)
        else:
            return json.dumps(result)
