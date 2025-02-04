import os
import json
import select
import statistics
import subprocess
import time
import sys

from collections import defaultdict
from typing import List, Tuple, Dict, Optional

from common import SIDEKICK_HOME
from experiment import Treatment, NetworkSetting, DirectNetworkSetting, Experiment

DEFAULT_DATA_HOME = f'{SIDEKICK_HOME}/data'


class RawDataFile:
    def __init__(
        self,
        treatment: Treatment,
        network_setting: NetworkSetting,
        data_home: str,
    ):
        self._treatment = treatment
        self._network_setting = network_setting
        base_dir = f'{data_home}/{network_setting.label()}'
        self.base_path = f'{base_dir}/{treatment.label()}'
        os.system(f'mkdir -p {base_dir}')
        os.system(f'touch {self.stdout_filename()}')
        os.system(f'touch {self.stderr_filename()}')
        os.system(f'touch {self.fulllog_filename()}')

    def treatment(self) -> str:
        return self._treatment.label()

    def network_setting(self) -> str:
        return self._network_setting.label()

    def stdout_filename(self) -> str:
        return f'{self.base_path}.stdout'

    def stderr_filename(self) -> str:
        return f'{self.base_path}.stderr'

    def fulllog_filename(self) -> str:
        return f'{self.base_path}.log'

    def cmd(self, data_size: int, num_trials: int, timeout: Optional[int]):
        cmd = ['sudo -E python3 emulation/main.py']
        if timeout is not None:
            cmd.append('--timeout')
            cmd.append(str(timeout))
        for key in self._network_setting.labels:
            cmd.append(f'--{key}')
            cmd.append(str(self._network_setting.settings[key]))
        cmd.append('-t')
        cmd.append(str(num_trials))
        cmd.append('--label')
        cmd.append(self._treatment.label())
        cmd += self._treatment.network_options
        cmd.append(self._treatment.protocol)
        cmd += self._treatment.protocol_options
        cmd.append('-n')
        cmd.append(str(data_size))
        return ' '.join(cmd)


class RawDataParser:
    def __init__(
        self,
        exp: Experiment,
        max_data_sizes: Dict[str, int],
        max_networks: Dict[str, int],
        data_home: str,
    ):
        """Parameters:
        - max_data_sizes: Map from treatment label -> data size index. For that
          treatment, only collects data points with data sizes up to that index.
          Used to collect data points with unreasonably low throughput. If
          labels are not provided, defaults to all data sizes.
        - max_networks: Map from treatment label -> network setting index. For
          that treatment, only collects data points with network settings up to
          that index. Used to avoid collecting data points with unreasonably
          low throughput. If labels are not provided, defaults to all data
          sizes.
        """
        self.exp = exp
        self.data = {}
        self.data_home = data_home

        max_ds = defaultdict(lambda: len(exp.data_sizes))
        max_ns = defaultdict(lambda: len(exp.network_settings))
        for treatment, ds in max_data_sizes.items():
            max_ds[treatment] = min(ds, len(exp.data_sizes))
        for treatment, ns in max_networks.items():
            max_ns[treatment] = min(ns, len(exp.network_settings))

        self._max_ds = max_ds
        self._max_ns = max_ns
        self._data_sizes = set(exp.data_sizes)
        self._reset()
        self._parse_files()

    def _reset(self):
        self.data = {}  # treatment -> network_setting -> data_size -> [value]
        for treatment in self.exp.treatments:
            self.data[treatment] = {}
            max_ns = self._max_ns[treatment]
            max_ds = self._max_ds[treatment]
            network_settings = self.exp.network_settings[:max_ns]
            data_sizes = self.exp.data_sizes[:max_ds]
            if self.exp.cartesian:
                for network_setting in network_settings:
                    self.data[treatment][network_setting] = {}
                    for data_size in data_sizes:
                        self.data[treatment][network_setting][data_size] = []
            else:
                assert len(network_settings) == len(data_sizes)
                for (ns, ds) in zip(network_settings, data_sizes):
                    self.data[treatment][ns] = {ds: []}

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


"""For executing mininet commands to collect missing data.
"""
class RawDataExecutor:
    def __init__(self, timeout):
        self.timeout = timeout

    def _collect_missing_data(
        self,
        missing_data: List[Tuple[RawDataFile, int, int]],
        chunk_size: int=10,
    ):
        print(len(missing_data))
        for file, data_size, num_missing in missing_data:
            remaining = num_missing
            while remaining != 0:
                num_trials = min(chunk_size, remaining)
                start = time.time()
                self._execute_chunk(file, data_size, num_trials)
                print(time.time() - start)
                remaining -= num_trials

    def _execute_chunk(self, file: RawDataFile, data_size: int, num_trials: int):
        # Start the process
        cmd = file.cmd(data_size, num_trials, timeout=self.timeout)
        print(cmd, end=' ')
        p = subprocess.Popen(
            cmd.split(' '),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SIDEKICK_HOME,
            text=True,
        )

        # Write process output to the appropriate logfiles
        with open(file.stdout_filename(), 'a') as stdout,\
             open(file.stderr_filename(), 'a') as stderr,\
             open(file.fulllog_filename(), 'a') as fulllog:
            while p.poll() is None:
                ready, _, _ = select.select([p.stdout, p.stderr], [], [])
                for stream in ready:
                    line = stream.readline()
                    if not line:
                        continue
                    if stream == p.stdout:
                        stdout.write(line)
                    if stream == p.stderr:
                        stderr.write(line)
                    fulllog.write(line)

            # Flush remaining data after process exit
            for line in p.stdout:
                stdout.write(line)
                fulllog.write(line)
            for line in p.stderr:
                stderr.write(line)
                fulllog.write(line)

        # Cleanup the process
        exitcode = p.wait()
        if exitcode != 0:
            print(f'execute error: {exitcode}')
            sys.exit(1)


class RawData(RawDataParser, RawDataExecutor):
    def __init__(
        self,
        exp: Experiment,
        execute=False,
        max_retries=5,
        max_data_sizes: Dict[str, int]={},
        max_networks: Dict[str, int]={},
        data_suffix: str='',
    ):
        """Parameters:
        - execute: Whether to collect missing data points.
        - max_retries: Maximum number of times to retry collecting missing data
          points after the first attempt.
        - max_data_sizes: Map from treatment label -> data size index. For that
          treatment, only collects data points with data sizes up to that index.
          Used to collect data points with unreasonably low throughput. If
          labels are not provided, defaults to all data sizes.
        - max_networks: Map from treatment label -> network setting index. For
          that treatment, only collects data points with network settings up to
          that index. Used to avoid collecting data points with unreasonably
          low throughput. If labels are not provided, defaults to all data
          sizes.
        - data_suffix: The suffix of the directory to {SIDEKICK_HOME}/data in
          which to parse raw data.
        """
        if len(data_suffix) > 0:
            data_home = f'{DEFAULT_DATA_HOME}/{data_suffix}'
        else:
            data_home = DEFAULT_DATA_HOME
        RawDataParser.__init__(self, exp, max_data_sizes=max_data_sizes,
            max_networks=max_networks, data_home=data_home)
        RawDataExecutor.__init__(self, exp.timeout)

        for i in range(max_retries):
            missing_data = self._find_missing_data()
            if len(missing_data) == 0 or not execute:
                break
            self._collect_missing_data(missing_data)
            self._reset()
            self._parse_files()

        # Print remaining missing data
        for file, data_size, num_missing in missing_data:
            print('MISSING:', file.cmd(data_size, num_missing, exp.timeout))

    def _find_missing_data(self) -> List[Tuple[RawDataFile, int, int]]:
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
                        missing_data.append((file, data_size, num_missing))
        return missing_data


class DirectRawData(RawDataParser, RawDataExecutor):
    def __init__(
        self,
        exp: Experiment,
        execute=False,
        max_retries=10,
        max_num_timeouts=1,
        data_suffix: str='',
    ):
        """Parameters:
        - execute: Whether to collect missing data points.
        - max_retries: Maximum number of times to retry collecting missing data
          points after the first attempt.
        - data_suffix: The suffix of the directory to {SIDEKICK_HOME}/data in
          which to parse raw data.
        """
        if len(data_suffix) > 0:
            data_home = f'{DEFAULT_DATA_HOME}/{data_suffix}'
        else:
            data_home = DEFAULT_DATA_HOME
        RawDataParser.__init__(self, exp, max_data_sizes={}, max_networks={},
            data_home=data_home)
        RawDataExecutor.__init__(self, exp.timeout)

        for i in range(max_retries):
            treatments = self.exp.get_treatments()
            missing_data = []
            for treatment in treatments:
                missing_data += self._find_missing_data(
                    treatment, max_num_timeouts)
            if len(missing_data) == 0 or not execute:
                break
            self._collect_missing_data(missing_data)
            self._reset()
            self._parse_files()

        # Print remaining missing data
        for file, data_size, num_missing in missing_data:
            print('MISSING:', file.cmd(data_size, num_missing, exp.timeout))

    def _find_missing_data(
        self, treatment: Treatment, max_num_timeouts: int,
    ) -> List[Tuple[RawDataFile, int, int]]:
        missing_data = []
        treatment_data = self.data[treatment.label()]

        # The length of the connection increases for larger delays, bw,
        # and loss. BFS within the provided parameter space until the
        # connection time exceeds a threshold MAX_TRIAL_TIME, in seconds.
        # The number of retries may need to be increased to explore the full
        # parameter space in a single execution.
        xs = self.exp.network_losses
        ys = self.exp.network_delays
        zs = self.exp.network_bws
        visited = set()
        queue = [(0, 0, 0)]
        while len(queue) > 0:
            i, j, k = queue.pop(0)
            if (i, j, k) in visited:
                continue
            visited.add((i, j, k))

            # Get the existing value for this data point.
            ns = DirectNetworkSetting(loss=xs[i], delay=ys[j], bw=zs[k])
            network_data = treatment_data[ns.label()]
            assert len(network_data) == 1
            data_size, outputs = next(iter(network_data.items()))

            # Count the number of timeouts in the existing outputs.
            # If at least half of the expected trials are timeouts, then
            # skip the remaining trials and adjacent data points.
            num_timeouts = 0
            for output in outputs:
                if 'timeout' in output and output['timeout']:
                    num_timeouts += 1
            if num_timeouts >= max_num_timeouts:
                continue

            # If there are any trials remaining, then execute the data point
            # (and don't explore more).
            num_missing = self.exp.num_trials - len(outputs)
            if num_missing > 0:
                file = RawDataFile(treatment, ns, self.data_home)
                missing_data.append((file, data_size, num_missing))
                continue

            # Else the data point has all its trials complete. Get the list
            # of data points that would be +1 from this point within bounds.
            to_visit = []
            if i+1 < len(xs):
                to_visit.append((i+1, j, k))
            if j+1 < len(ys):
                to_visit.append((i, j+1, k))
            if k+1 < len(zs):
                to_visit.append((i, j, k+1))
            queue += to_visit

        return missing_data


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
    def __init__(self, data: RawData, metric: str):
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
