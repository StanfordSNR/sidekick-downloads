import json
from datetime import datetime


class HTTPBenchmarkResult:
    def __init__(self, label: str, protocol: str,
                 data_size: int, cca: str, pep: bool):
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
        self.inputs['num_trials'] += 1
        self.outputs.append({
            'success': False,
        })

    def set_success(self, success: bool):
        self.outputs[-1]['success'] = success

    def set_timeout(self, timeout: bool):
        self.outputs[-1]['timeout'] = timeout

    def set_time_s(self, time_s: float):
        self.outputs[-1]['time_s'] = time_s
        self.outputs[-1]['throughput_mbps'] = \
            8 * self.inputs['data_size'] / 1000000 / time_s

    def set_network_statistics(self, statistics):
        self.outputs[-1]['statistics'] = statistics

    def set_additional_data(self, data):
        self.outputs[-1]['additional_data'] = data

    def print(self, pretty_print=False):
        result = {
            'inputs': self.inputs,
            'outputs': self.outputs,
        }
        if pretty_print:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result))
