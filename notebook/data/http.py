import os
import json
import select
import statistics
import subprocess
import time
import sys

from collections import defaultdict
from typing import List, Tuple, Dict, Optional

from common import SIDEKICK_HOME, DATA_HOME
from data import RawDataFile, RawDataExecutor
from experiment import Treatment, NetworkSetting, Experiment


class HTTPExperiment(Experiment):
    def __init__(self,
                 num_trials: int,
                 data_sizes: List[int],
                 treatments: List[Treatment],
                 network_settings: List[NetworkSetting],
                 timeout: Optional[int]=None):
        super().__init__(treatments, network_settings)
        self.num_trials = num_trials
        self.data_sizes = data_sizes
        self.timeout = timeout

    def to_raw_data(self, execute: bool=False, max_retries: int=5,
                    max_data_sizes: Dict[str, int]={},
                    max_networks: Dict[str, int]={}, data_suffix: str=''):
        return HTTPRawData(self, execute=execute, max_retries=max_retries,
                       max_networks=max_networks, data_suffix=data_suffix,
                       max_data_sizes=max_data_sizes)


class HTTPRawDataParser:
    def __init__(
        self,
        exp: HTTPExperiment,
        max_networks: Dict[str, int],
        max_data_sizes: Dict[str, int],
        data_home: str,
    ):
        """Parameters:
        - max_networks: Map from treatment label -> network setting index. For
          that treatment, only collects data points with network settings up to
          that index. Used to avoid collecting data points with unreasonably
          low throughput. If labels are not provided, defaults to all data
          sizes.
        """
        self.exp = exp
        self.data = {}
        self.data_home = data_home

        max_ns = defaultdict(lambda: len(exp.network_settings))
        max_ds = defaultdict(lambda: len(exp.data_sizes))
        for treatment, ns in max_networks.items():
            max_ns[treatment] = min(ns, len(exp.network_settings))
        for treatment, ds in max_data_sizes.items():
            max_ds[treatment] = min(ds, len(exp.data_sizes))

        self._max_ns = max_ns
        self._max_ds = max_ds
        self._reset()
        self._parse_files()

    def _reset(self):
        self.data = {}  # treatment -> network_setting -> data_size -> [value]
        for treatment in self.exp.treatments:
            self.data[treatment] = {}
            max_ns = self._max_ns[treatment]
            network_settings = self.exp.network_settings[:max_ns]
            for network_setting in network_settings:
                self.data[treatment][network_setting] = {}
                max_ds = self._max_ds[treatment]
                for data_size in self.exp.data_sizes[:max_ds]:
                    self.data[treatment][network_setting][data_size] = []

    def _parse_files(self):
        for treatment in self.exp.get_treatments():
            for network_setting in self.exp.get_network_settings():
                file = RawDataFile(treatment, network_setting, self.data_home)
                self._parse_file(file)

    def _parse_file(self, file: RawDataFile):
        filename = file.stdout_filename()
        with open(filename) as f:
            for line in f:
                line = line.strip()
                try:
                    line = json.loads(line)
                except Exception as e:
                    # Ignore non-JSON line
                    continue
                for data_size, output in self._parse_line(line):
                    self._maybe_add(
                        file.treatment(),
                        file.network_setting(),
                        data_size,
                        output,
                    )

    def _parse_line(self, line):
        """
        Input: Parsed JSON line from experiment logs
        Output: The parsed data size and outputs
        """
        data_size = line['inputs']['data_size']
        for output in line['outputs']:
            if output['success']:
                yield (data_size, output)
            elif 'timeout' in output and output['timeout']:
                # If the experiment would timeout with our current settings,
                # then this counts as a valid data point.
                # Later validation parses the data point for a metric.
                timeout = self.exp.timeout
                if timeout is not None and output['time_s'] >= timeout:
                    yield (data_size, output)

    def _maybe_add(self, treatment: str, network_setting: str, data_size: int,
                  value) -> bool:
        # Don't add the value if it is not one of the requested data points
        if treatment not in self.data:
            return False
        if network_setting not in self.data[treatment]:
            return False
        if data_size not in self.data[treatment][network_setting]:
            return False

        # Add the value if number of trials not exceeded
        values = self.data[treatment][network_setting][data_size]
        if len(values) >= self.exp.num_trials:
            return False
        values.append(value)
        return True


class HTTPRawData(HTTPRawDataParser, RawDataExecutor):
    def __init__(
        self,
        exp: HTTPExperiment,
        execute=False,
        max_retries=5,
        max_networks: Dict[str, int]={},
        max_data_sizes: Dict[str, int]={},
        data_suffix: str='',
    ):
        """Parameters:
        - execute: Whether to collect missing data points.
        - max_retries: Maximum number of times to retry collecting missing data
          points after the first attempt.
        - max_networks: Map from treatment label -> network setting index. For
          that treatment, only collects data points with network settings up to
          that index. Used to avoid collecting data points with unreasonably
          low throughput. If labels are not provided, defaults to all data
          sizes.
        - data_suffix: The suffix of the directory to {SIDEKICK_HOME}/data in
          which to parse raw data.
        """
        if len(data_suffix) > 0:
            data_home = f'{DATA_HOME}/{data_suffix}'
        else:
            data_home = DATA_HOME
        HTTPRawDataParser.__init__(self, exp, max_data_sizes=max_data_sizes,
            max_networks=max_networks, data_home=data_home)

        for i in range(max_retries):
            missing_data = self._find_missing_data(exp.timeout)
            if len(missing_data) == 0 or not execute:
                break
            self._collect_missing_data(missing_data)
            self._reset()
            self._parse_files()

        # Print remaining missing data
        for _, cmd in missing_data:
            print('MISSING:', cmd)

    def _find_missing_data(self, timeout) -> List[Tuple[RawDataFile, str]]:
        missing_data = []
        for treatment in self.exp.get_treatments():
            treatment_data = self.data[treatment.label()]
            for network_setting in self.exp.get_network_settings():
                network_data = treatment_data.get(network_setting.label())
                if network_data is None:
                    continue
                file = RawDataFile(treatment, network_setting, self.data_home)
                for data_size, size_data in sorted(network_data.items()):
                    num_results = len(size_data)
                    num_missing = self.exp.num_trials - num_results
                    if num_missing > 0:
                        cmd = file.cmd(data_size=data_size, num_trials=num_missing, timeout=timeout)
                        missing_data.append((file, cmd))
        return missing_data

    def to_plottable_data(self, metric):
        return PlottableData(self, metric)


class PlottableDataPoint:
    def __init__(self, raw_data):
        self.raw_data = raw_data
        self.sorted_data = list(sorted(raw_data))
        self.n = len(raw_data)
        if self.n == 0:
            self.mean = None
            self.std = None
        elif self.n == 1:
            self.mean = statistics.mean(raw_data)
            self.std = None
        else:
            self.mean = statistics.mean(raw_data)
            self.std = statistics.stdev(raw_data)

    def p(self, pct):
        assert 0 <= pct < 100
        if self.n == 0:
            return None
        i = int(self.n * pct / 100.0)
        return self.sorted_data[i]


class PlottableData:
    def __init__(self, data: HTTPRawData, metric):
        self.data = defaultdict(lambda: defaultdict(lambda: {}))
        self.exp = data.exp
        self.treatments = data.exp.treatments
        self.network_settings = data.exp.network_settings
        self.data_sizes = data.exp.data_sizes
        self.metric = metric
        for treatment in self.treatments:
            treatment_data = data.data[treatment]
            for network_setting in self.network_settings:
                results = treatment_data.get(network_setting)
                if results is None:
                    continue
                for data_size, outputs in results.items():
                    outputs = list(filter(lambda output:
                        'timeout' not in output or not output['timeout'], outputs))
                    if len(outputs) == 0:
                        continue
                    # Parse the metric value for each output
                    if isinstance(metric, str):
                        values = [output[metric] for output in outputs]
                    else:
                        values = [metric(output) for output in outputs]
                    pdp = PlottableDataPoint(values)
                    self.data[treatment][network_setting][data_size] = pdp
