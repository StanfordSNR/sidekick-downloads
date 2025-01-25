import json
import time
import threading
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple
import re

from common import *


class Protocol(Enum):
    QUIC = 0
    TCP = 1
    TCP_IPERF3 = 2
    CloudflareQUIC = 3
    PicoQUIC = 4


class BenchmarkResult:
    def __init__(self, label: str, protocol: Protocol,
                 data_size: int, cca: str, pep: bool):
        self.inputs = {
            'label': label,
            'protocol': protocol.name,
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


class BaseBenchmark:
    def __init__(self, net):
        self.net = net

    def start_sidekick(self):
        pass

class PicoQUICBenchmark(BaseBenchmark):
    def __init__(self, net, n: str, cca: str, certfile=None, keyfile=None):
        super().__init__(net)
        self.n = n
        self.cca = cca
        self.server_ip = self.net.h2.IP()
        self.certfile = certfile
        self.keyfile = keyfile

    def restart_server(self, logfile):
        WARN('Restarting picoquic-server')
        self.net.h2.cmd('killall picoquic_sample')
        self.start_server(logfile=logfile)

    def start_server(self, logfile):
        base = 'deps/picoquic'
        cmd = f'./{base}/picoquic_sample '\
              f'server '\
              f'4433 '\
              f'{self.certfile} '\
              f'{self.keyfile} '\
              f'. '\
              f'{self.n} '\
              f'{self.cca}'

        DEBUG(f'{self.net.h2.name} {cmd}')
        self.net.h2.cmd(cmd + ' &')
        time.sleep(2)

        '''
        TODO FIGURE OUT WHY POPEN ISN'T STARTING for picoquic
        condition = threading.Condition()
        def notify_when_ready(line):
            if 'serving' in line.lower():
                with condition:
                    condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=SETUP_TIMEOUT)
            if not notified:
                WARN("Server did not print expected output; continuing anyway")
                # raise TimeoutError(f'start_server timeout {SETUP_TIMEOUT}s')
        '''

    def run_client(self, logfile, timeout) -> Optional[Tuple[int, float]]:
        """Returns the status code and runtime (seconds) of the GET request.
        """
        base = 'deps/picoquic'
        cmd = f'./{base}/picoquic_sample '\
              f'client '\
              f'{self.server_ip} '\
              f'4433 '\
              f'/tmp '\
              f'{self.cca} '\
              f'{self.n}.html '
        if timeout is None:
            DEBUG(f'{self.net.h1.name} {cmd}')
            output = self.net.h1.cmd(cmd)
        else:
            DEBUG(f'{self.net.h1.name} timeout {timeout} {cmd}')
            output = self.net.h1.cmd(f"timeout {timeout} {cmd}")

        result = []
        def parse_result(line):
            if 'complete' not in line:
                return
            try:
                match = re.search(r'\d+\.\d+ seconds', line).group(0)
                time_s = float(match.split(' ')[0])
                result.append(time_s)
            except:
                pass

        print(output)
        for line in output.split('\n'):
            parse_result(line)

        # TODO figure out why popen isn't working
        # timeout_flag = self.net.popen(self.net.h1, cmd, background=False,
        #     console_logger=DEBUG, logfile=logfile, func=parse_result,
        #     timeout=timeout, raise_error=False)

        if len(result) == 0:
            WARN('PicoQUIC client failed to return result')
            if timeout is not None:
                WARN('assuming picoquic timeout')
                return (HTTP_TIMEOUT_STATUSCODE, timeout)
            else:
                return None
        elif len(result) > 1:
            WARN(f'PicoQUIC client returned multiple results {result}')
        else:
            return (HTTP_OK_STATUSCODE, result[0])

    def run(self, label, logdir, num_trials, timeout, network_statistics):

        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials
        # allow N "no output" errors without decrementing trials
        num_errors_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = BenchmarkResult(
                label=label,
                protocol=Protocol.PicoQUIC,
                data_size=self.n,
                cca=self.cca,
                pep=False,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(
                    logfile=f'{logdir}/{CLIENT_LOGFILE}',
                    timeout=timeout,
                )

                # Error
                if output is None:
                    ERROR('no output')
                    self.restart_server(f'{logdir}/{SERVER_LOGFILE}')
                    num_errors_left -= 1
                    if num_errors_left == 0:
                        num_trials_left = 0
                    continue

                # Success
                if network_statistics:
                    statistics = self.net.snapshot_statistics()
                    result.set_network_statistics(statistics)
                status_code, time_s = output
                result.set_success(status_code == HTTP_OK_STATUSCODE)
                result.set_timeout(status_code == HTTP_TIMEOUT_STATUSCODE)
                result.set_time_s(time_s)

                total_time_s += time_s
                num_trials_left -= 1
            result.print()

class CloudflareQUICBenchmark(BaseBenchmark):
    def __init__(self, net, n: str, cca: str, certfile=None, keyfile=None):
        super().__init__(net)
        self.n = n
        self.cca = cca
        self.server_ip = self.net.h2.IP()
        self.certfile = certfile
        self.keyfile = keyfile

    def restart_server(self, logfile):
        WARN('Restarting quiche-server')
        self.net.h2.cmd('killall quiche-server')
        self.start_server(logfile=logfile)

    def start_server(self, logfile):
        base = 'deps/quiche/target/release'
        cmd = f'./{base}/quiche-server '\
              f'--cert={self.certfile} '\
              f'--key={self.keyfile} '\
              f'--cc-algorithm {self.cca} ' \
              f'--listen {self.server_ip}:4433'

        condition = threading.Condition()
        def notify_when_ready(line):
            if 'listening' in line.lower():
                with condition:
                    condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=SETUP_TIMEOUT)
            if not notified:
                raise TimeoutError(f'start_server timeout {SETUP_TIMEOUT}s')

    def run_client(self, logfile, timeout) -> Optional[Tuple[int, float]]:
        """Returns the status code and runtime (seconds) of the GET request.
        """
        base = 'deps/quiche/target/release'
        cmd = f'./{base}/quiche-client '\
              f'--no-verify '\
              f'--method GET '\
              f'--cc-algorithm {self.cca} ' \
              f'-- https://{self.server_ip}:4433/{self.n}'

        result = []
        timed_out = False
        def parse_result(line):
            if 'response(s) received in ' not in line:
                return
            if 'Not found' in line:
                return
            if 'timed out' in line:
                timed_out = True
            try:
                match = re.search(r'received in \d+\.\d+', line).group(0)
                time_s = float(match.split(' ')[-1])
                result.append(time_s)
            except:
                pass


        timeout_flag = self.net.popen(self.net.h1, cmd, background=False,
            console_logger=DEBUG, logfile=logfile, func=parse_result,
            timeout=timeout, raise_error=False)

        if timed_out:
            # Max idle timeout reached when there have been no packets received for
            # N seconds (default: 30); this implies that something went
            # wrong with the server or client, which should be distinguished from
            # a timeout due to insufficient bandwidth.
            WARN('Cloudflare QUIC client failed (idle timeout)')
            return None
        elif timeout_flag:
            return (HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            WARN('Cloudflare QUIC client failed to return result')
        elif len(result) > 1:
            WARN(f'Cloudflare QUIC client returned multiple results {result}')
        else:
            return (HTTP_OK_STATUSCODE, result[0])

    def run(self, label, logdir, num_trials, timeout, network_statistics):
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials
        # allow N "no output" errors without decrementing trials
        num_errors_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = BenchmarkResult(
                label=label,
                protocol=Protocol.CloudflareQUIC,
                data_size=self.n,
                cca=self.cca,
                pep=False,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(
                    logfile=f'{logdir}/{CLIENT_LOGFILE}',
                    timeout=timeout,
                )

                # Error
                if output is None:
                    ERROR('no output')
                    self.restart_server(f'{logdir}/{SERVER_LOGFILE}')
                    num_errors_left -= 1
                    if num_errors_left == 0:
                        num_trials_left = 0
                    continue

                # Success
                if network_statistics:
                    statistics = self.net.snapshot_statistics()
                    result.set_network_statistics(statistics)
                status_code, time_s = output
                result.set_success(status_code == HTTP_OK_STATUSCODE)
                result.set_timeout(status_code == HTTP_TIMEOUT_STATUSCODE)
                result.set_time_s(time_s)

                total_time_s += time_s
                num_trials_left -= 1
            result.print()

class QUICBenchmark(BaseBenchmark):
    def __init__(self, net, n: str, cca: str, certfile=None, keyfile=None):
        super().__init__(net)
        self.n = n
        self.cca = cca
        self.certfile = certfile
        self.keyfile = keyfile
        self.server_ip = self.net.h2.IP()

        # Create cache dir
        # self.cache_dir = '/tmp/quic-data/www.example.org'
        # filename = f'{self.cache_dir}/index.html'
        # net.popen(None, f'mkdir -p {self.cache_dir}', console_logger=DEBUG)
        # net.popen(None, f'head -c {n} /dev/urandom > {filename}', console_logger=DEBUG)

    def start_server(self, logfile):
        base = 'deps/chromium/src'
        cmd = f'./{base}/out/Default/quic_server '\
              f'--certificate_file={self.certfile} '\
              f'--key_file={self.keyfile} '\
              f'--num_cached_bytes={self.n}'

        condition = threading.Condition()
        def notify_when_ready(line):
            if 'Serving' in line:
                with condition:
                    condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=SETUP_TIMEOUT)
            if not notified:
                raise TimeoutError(f'start_server timeout {SETUP_TIMEOUT}s')

    def run_client(self, logfile, timeout) -> Optional[Tuple[int, float]]:
        """Returns the status code and runtime (seconds) of the GET request.
        """
        base = 'deps/chromium/src'
        cmd = f'./{base}/out/Default/quic_client '\
              f'--allow_unknown_root_cert '\
              f'--host={self.net.h2.IP()} --port=6121 '\
              f'https://www.example.org/{self.n} '

        # Add the congestion control algorithm options
        cca_to_option = {
            'cubic': 'BYTE',
            'reno': 'RENO',
            'bbr1': 'TBBR',
            'bbr': 'B2ON',
        }
        if self.cca in cca_to_option:
            option = cca_to_option[self.cca]
            cmd += f'--client_connection_options={option} '
            cmd += f'--connection_options={option} '

        result = []
        def parse_result(line):
            if not line.startswith('[QUIC_CLIENT]'):
                return
            try:
                line = line.split(' ')[1:]
                line = [kv.split('=') for kv in line]
                assert line[0][0] == 'status_code'
                assert line[1][0] == 'time_s'
                status_code = int(line[0][1])
                time_s = float(line[1][1].strip()[:-1])  # output ends in "s"
                result.append((status_code, time_s))
            except:
                pass

        timeout_flag = self.net.popen(self.net.h1, cmd, background=False,
            console_logger=DEBUG, logfile=logfile, func=parse_result,
            timeout=timeout)
        if timeout_flag:
            return (HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            # E.g., 404 not found
            WARN('QUIC client failed to return result')
        elif len(result) > 1:
            WARN(f'QUIC client returned multiple results {result}')
        else:
            return result[0]

    def run(self, label, logdir, num_trials, timeout, network_statistics):
        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = BenchmarkResult(
                label=label,
                protocol=Protocol.QUIC,
                data_size=self.n,
                cca=self.cca,
                pep=False,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(
                    logfile=f'{logdir}/{CLIENT_LOGFILE}',
                    timeout=timeout,
                )

                # Error
                if output is None:
                    ERROR('no output')
                    num_trials_left -= 1
                    continue

                # Success
                if network_statistics:
                    statistics = self.net.snapshot_statistics()
                    result.set_network_statistics(statistics)
                status_code, time_s = output
                result.set_success(status_code == HTTP_OK_STATUSCODE)
                result.set_timeout(status_code == HTTP_TIMEOUT_STATUSCODE)
                result.set_time_s(time_s)

                total_time_s += time_s
                num_trials_left -= 1
            result.print()


class TCPBenchmark(BaseBenchmark):
    def __init__(
        self,
        net,
        n: int,
        cca: str,
        pep: bool,
        certfile=None,
        keyfile=None,
    ):
        super().__init__(net)
        net.set_tcp_congestion_control(cca)

        self.n = n
        self.cca = cca
        self.pep = pep
        self.certfile = certfile
        self.keyfile = keyfile
        self.server_ip = self.net.h2.IP()

    def start_server(self, logfile):
        cmd = f'python3 webserver/http_server.py --server-ip {self.server_ip} '\
              f'--certfile {self.certfile} --keyfile {self.keyfile} '\
              f'-n {self.n}'

        condition = threading.Condition()
        def notify_when_ready(line):
            if 'Serving' in line:
                with condition:
                    condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=SETUP_TIMEOUT)
            if not notified:
                raise TimeoutError(f'start_server timeout {SETUP_TIMEOUT}s')

    def run_client(self, logfile, timeout) -> Optional[Tuple[int, float]]:
        """Returns the status code and runtime (seconds) of the GET request.
        """
        cmd = f'python3 webserver/http_client.py --server-ip {self.server_ip} '\
              f'-n {self.n}'

        result = []
        def parse_result(line):
            if not line.startswith('[TCP_CLIENT]'):
                return
            try:
                line = line.split(' ')[1:]
                line = [kv.split('=') for kv in line]
                assert line[0][0] == 'status_code'
                assert line[1][0] == 'time_s'
                status_code = int(line[0][1])
                time_s = float(line[1][1])
                result.append((status_code, time_s))
            except:
                pass

        timeout_flag = self.net.popen(self.net.h1, cmd, background=False,
            console_logger=DEBUG, logfile=logfile, func=parse_result,
            timeout=timeout)
        if timeout_flag:
            return (HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            WARN('TCP client failed to return result')
        elif len(result) > 1:
            WARN(f'TCP client returned multiple results {result}')
        else:
            return result[0]

    def run(self, label, logdir, num_trials, timeout, network_statistics):
        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Start the TCP PEP
        if self.pep:
            self.net.start_tcp_pep(logfile=f'{logdir}/{ROUTER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = BenchmarkResult(
                label=label,
                protocol=Protocol.TCP,
                data_size=self.n,
                cca=self.cca,
                pep=self.pep,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(
                    logfile=f'{logdir}/{CLIENT_LOGFILE}',
                    timeout=timeout,
                )

                # Error
                if output is None:
                    ERROR('no output')
                    num_trials_left -= 1
                    continue

                # Success
                if network_statistics:
                    statistics = self.net.snapshot_statistics()
                    result.set_network_statistics(statistics)
                status_code, time_s = output
                result.set_success(status_code == HTTP_OK_STATUSCODE)
                result.set_timeout(status_code == HTTP_TIMEOUT_STATUSCODE)
                result.set_time_s(time_s)

                total_time_s += time_s
                num_trials_left -= 1
            result.print()


# \NOTE using `popen` on the network as in the other benchmarks
# did not reliably work for some older kernel versions, so we use
# hX.cmd(XX) for this benchmark instead.
class Iperf3Benchmark(BaseBenchmark):
    def __init__(
        self,
        net,
        n: int,
        cca: str,
        pep: bool,
    ):
        super().__init__(net)
        self.n = n
        self.pep = pep
        self.cca = cca
        net.set_tcp_congestion_control(cca)

    def start_server(self):
        cmd = 'iperf3 -s &'
        self.net.h2.cmd(cmd)

    def stop_server(self):
        self.net.h2.cmd('killall iperf3')

    def run_client(self, outfile, timeout):
        cmd = f'iperf3 -c {self.net.h2.IP()} '
        cmd += f'-n {self.n} '
        cmd += f'--json > {outfile}'
        self.net.h1.cmd(cmd)

    def run(self, label, logdir, num_trials, timeout, network_statistics,
            additional_data):
        self.start_server()
        if self.pep:
            self.net.start_tcp_pep()
        num_trials_left = num_trials

        while num_trials_left > 0:

            result = BenchmarkResult(
                label=label,
                protocol=Protocol.TCP_IPERF3,
                data_size=self.n,
                cca=self.cca,
                pep=self.pep,
            )

            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                success = self.run_client(
                            outfile = 'tmp.json',
                            timeout=timeout,
                        )

                if network_statistics:
                    statistics = self.net.snapshot_statistics()
                    result.set_network_statistics(statistics)

                result.set_success(True)
                json_data = json.load(open('tmp.json', 'r'))
                os.system('sudo rm tmp.json')
                if additional_data:
                    result.set_additional_data(json_data)
                result.set_time_s(json_data['end']['sum_received']['seconds'])
                total_time_s += total_time_s
                num_trials_left -= 1

            result.print()

        self.stop_server()

