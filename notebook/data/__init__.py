import os
import select
import subprocess
import time
import sys

from common import SIDEKICK_HOME
from typing import List, Tuple, Optional
from experiment import Treatment, NetworkSetting


class RawDataFile:
    def __init__(
        self,
        treatment: Treatment,
        network_setting: NetworkSetting,
        data_home: Optional[str]=None,
    ):
        self._treatment = treatment
        self._network_setting = network_setting
        if data_home:
            base_dir = f'{data_home}/{treatment.protocol}/{network_setting.label()}'
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

    def cmd(self,
            data_size: Optional[int]=None,
            num_trials: Optional[int]=None,
            timeout: Optional[int]=None,
            duration: Optional[int]=None,
            debug: bool=False,
            logdir: Optional[str]=None,
            num_clients: Optional[int]=None,
            client_quacker: Optional[int]=None):
        cmd = ['sudo -E python3 emulation/main.py']
        if timeout is not None:
            cmd.append('--timeout')
            cmd.append(str(timeout))
        for key in self._network_setting.labels:
            cmd.append(f'--{key}')
            cmd.append(str(self._network_setting.settings[key]))
        if num_trials is not None:
            cmd.append('-t')
            cmd.append(str(num_trials))
        if debug:
            cmd.append('--debug')
        if logdir:
            cmd.append('--logdir')
            cmd.append(logdir)
        cmd.append('--label')
        cmd.append(self._treatment.label())
        cmd += self._treatment.network_options
        cmd.append('--network-statistics')
        cmd.append(self._treatment.protocol)
        cmd += self._treatment.protocol_options
        if data_size is not None:
            cmd.append('-n')
            cmd.append(str(data_size))
        if duration is not None:
            cmd.append('--duration')
            cmd.append(str(duration))
        if num_clients is not None:
            cmd.append('--num-clients')
            cmd.append(str(num_clients))
        if client_quacker is not None:
            cmd.append('--client-quacker')
            cmd.append(str(client_quacker))
        return ' '.join(cmd)


"""For executing mininet commands to collect missing data.
"""
class RawDataExecutor:
    def _collect_missing_data(
        self,
        missing_data: List[Tuple[RawDataFile, str]],
        retry: int=3,
    ):
        print(len(missing_data))
        for file, cmd in missing_data:
            start = time.time()
            self._execute_chunk(file, cmd, retry)
            print(time.time() - start)

    def _execute_chunk(self, file: RawDataFile, cmd: str, retry: int):
        # Start the process
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
            if retry - 1 > 0:
                print(f'Retrying')
                self._execute_chunk(file, cmd, retry - 1)
            else:
                print(f'Continuing to next experiment')
            # sys.exit(1)
