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


class MulticastExperiment(Experiment):
    def __init__(self,
                 duration: int,
                 treatments: List[Treatment],
                 network_setting: NetworkSetting,
                 num_clients: List[int]):
        super().__init__(treatments, [network_setting])
        self.duration = duration
        self.num_clients = num_clients

    def to_raw_data(self, execute: bool=False, data_suffix: str=''):
        return MulticastRawData(self, execute=execute, data_suffix=data_suffix)


class MulticastRawDataParser:
    def __init__(
        self,
        exp: MulticastExperiment,
        data_home: str,
    ):
        self.exp = exp
        self.data_home = data_home
        self._reset()
        self._parse_files()

    def _reset(self):
        self.data = {}  # treatment -> num_clients -> output
        for treatment in self.exp.get_treatments():
            self.data[treatment.label()] = {}
            for num_clients in self.exp.num_clients:
                self.data[treatment.label()][num_clients] = None

    def _parse_files(self):
        for treatment in self.exp.get_treatments():
            assert len(self.exp.get_network_settings()) == 1
            network_setting = self.exp.get_network_settings()[0]
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
                output = line['outputs'][0]
                if not output['success']:
                    continue
                num_clients = len(output['client_ids'])
                duration = output.get('time_s')
                treatment = file.treatment()
                if treatment not in self.data:
                    continue
                if duration < self.exp.duration:
                    continue
                if num_clients in self.data[treatment]:
                    # Good data point
                    self.data[treatment][num_clients] = output


class MulticastRawData(MulticastRawDataParser, RawDataExecutor):
    def __init__(
        self,
        exp: MulticastExperiment,
        execute=False,
        max_retries=5,
        data_suffix: str='',
    ):
        """Parameters:
        - execute: Whether to collect missing data points.
        - data_suffix: The suffix of the directory to {SIDEKICK_HOME}/data in
          which to parse raw data.
        """
        if len(data_suffix) > 0:
            data_home = f'{DATA_HOME}/{data_suffix}'
        else:
            data_home = DATA_HOME
        MulticastRawDataParser.__init__(self, exp, data_home=data_home)

        for i in range(max_retries):
            missing_data = self._find_missing_data(exp.duration)
            if len(missing_data) == 0 or not execute:
                break
            self._collect_missing_data(missing_data)
            self._reset()
            self._parse_files()

        # Print remaining missing data
        for _, cmd in missing_data:
            print('MISSING:', cmd)

    def _find_missing_data(self, duration) -> List[Tuple[RawDataFile, str]]:
        missing_data = []
        assert len(self.exp.get_network_settings()) == 1
        network_setting = self.exp.get_network_settings()[0]
        for treatment in self.exp.get_treatments():
            for num_clients in self.exp.num_clients:
                result = self.data[treatment.label()].get(num_clients)
                if result:
                    continue
                file = RawDataFile(treatment, network_setting, self.data_home)
                if treatment.label() == 'baseline':
                    client_quacker = None
                else:
                    client_quacker = num_clients
                cmd = file.cmd(duration=duration, num_clients=num_clients,
                    client_quacker=client_quacker)
                missing_data.append((file, cmd))
        return missing_data
