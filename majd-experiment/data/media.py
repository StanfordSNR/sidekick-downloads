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


class MediaExperiment(Experiment):
    def __init__(self,
                 duration: int,
                 treatments: List[Treatment],
                 network_setting: NetworkSetting):
        super().__init__(treatments, [network_setting])
        self.duration = duration

    def to_raw_data(self, execute: bool=False, data_suffix: str=''):
        return MediaRawData(self, execute=execute, data_suffix=data_suffix)


class MediaRawDataParser:
    def __init__(
        self,
        exp: MediaExperiment,
        data_home: str,
    ):
        self.exp = exp
        self.data = {}
        self.data_home = data_home
        self._parse_files()

    def _reset(self):
        self.data = {}  # treatment -> output

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
                duration = output.get('time_s')
                if duration >= self.exp.duration:
                    # Good data point
                    self.data[file.treatment()] = output
                    break


class MediaRawData(MediaRawDataParser, RawDataExecutor):
    def __init__(
        self,
        exp: MediaExperiment,
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
        MediaRawDataParser.__init__(self, exp, data_home=data_home)

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
        for treatment in self.exp.get_treatments():
            if treatment.label() in self.data:
                continue
            assert len(self.exp.get_network_settings()) == 1
            network_setting = self.exp.get_network_settings()[0]
            file = RawDataFile(treatment, network_setting, self.data_home)
            cmd = file.cmd(duration=duration)
            missing_data.append((file, cmd))
        return missing_data
