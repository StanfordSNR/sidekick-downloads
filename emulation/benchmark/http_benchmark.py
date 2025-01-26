import time
import threading
from abc import ABC
from enum import Enum
from typing import Optional, Tuple
import re

import mininet

from common import *
from network import EmulatedNetwork
from .result import HTTPBenchmarkResult


class Protocol(Enum):
    TCP = 0
    GOOGLE_QUIC = 1
    CLOUDFLARE_QUIC = 2
    PICOQUIC = 3


class HTTPDownloadBenchmark(ABC):
    def __init__(
        self,
        net: EmulatedNetwork,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
    ):
        """
        File download benchmark where the HTTPS client on the h1 host requests
        a certain number of application-layer bytes from the HTTPS server on
        the h2 host. Reports metrics such as the request latency and throughput.

        Subclasses of HTTPDownloadBenchmark must call this constructor.

        Parameters:
        - net: The mininet network to run the benchmark on. Requires an h1 and
          h2 host, and a p1 host if a proxy is configured.
        - data_size: The number of application-layer bytes transferred in the
          GET request.
        - cca: The congestion control algorithm used in the transport protocol.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        """
        self.net = net
        self._data_size = data_size
        self._cca = cca
        self._certfile = certfile
        self._keyfile = keyfile

    @property
    def client(self) -> mininet.node.Host:
        """The mininet host of the HTTPS client.
        """
        return self.net.h1

    @property
    def server(self) -> mininet.node.Host:
        """The mininet host of the HTTPS server.
        """
        return self.net.h2

    @property
    def data_size(self) -> int:
        """The data size, in bytes, transferred in the application-layer data
        of the GET request. Excludes HTTP headers.
        """
        return self._data_size

    @property
    def cca(self) -> str:
        """The congestion control algorithm used in the transport protocol.
        """
        return self._cca

    @property
    def certfile(self) -> int:
        """Path to the TLS/SSL certificate file
        """
        return self._certfile

    @property
    def keyfile(self) -> int:
        """Path to the TLS/SSL key file
        """
        return self._keyfile


class PicoQUICBenchmark(HTTPDownloadBenchmark):
    def __init__(
        self,
        net: EmulatedNetwork,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
    ):
        """
        Picoquic file download benchmark.

        Parameters:
        - net: The mininet network.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        """
        super().__init__(
            net=net, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile,
        )
        self.server_ip = self.net.h2.IP()

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
              f'{self.data_size} '\
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
              f'{self.data_size}.html '
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

        print(output, file=sys.stderr)
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

    def run(
        self, label, logdir, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:

        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials
        # allow N "no output" errors without decrementing trials
        num_errors_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = HTTPBenchmarkResult(
                label=label,
                protocol=Protocol.PICOQUIC.name,
                data_size=self.data_size,
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
        return result


class CloudflareQUICBenchmark(HTTPDownloadBenchmark):
    def __init__(
        self,
        net: EmulatedNetwork,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
    ):
        """
        Cloudflare QUIC file download benchmark.

        Parameters:
        - net: The mininet network.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        """
        super().__init__(
            net=net, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile,
        )
        self.server_ip = self.net.h2.IP()

    def restart_server(self, logfile):
        WARN('Restarting quiche-server')
        self.net.h2.cmd('killall quiche-server')
        self.start_server(logfile=logfile)

    def start_server(self, logfile):
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

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
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

        base = 'deps/quiche/target/release'
        cmd = f'./{base}/quiche-client '\
              f'--no-verify '\
              f'--method GET '\
              f'--cc-algorithm {self.cca} ' \
              f'-- https://{self.server_ip}:4433/{self.data_size}'

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

    def run(
        self, label, logdir, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Run the client
        result = HTTPBenchmarkResult(
            label=label,
            protocol=Protocol.CLOUDFLARE_QUIC.name,
            data_size=self.data_size,
            cca=self.cca,
            pep=False,
        )

        for _ in range(num_trials):
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
                continue

            # Success
            if network_statistics:
                statistics = self.net.snapshot_statistics()
                result.set_network_statistics(statistics)
            status_code, time_s = output
            result.set_success(status_code == HTTP_OK_STATUSCODE)
            result.set_timeout(status_code == HTTP_TIMEOUT_STATUSCODE)
            result.set_time_s(time_s)
        return result


class GoogleQUICBenchmark(HTTPDownloadBenchmark):
    def __init__(
        self,
        net: EmulatedNetwork,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
    ):
        """
        Google QUIC file download benchmark.

        Parameters:
        - net: The mininet network.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        """
        super().__init__(
            net=net, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile,
        )
        self.server_ip = self.net.h2.IP()

    def start_server(self, logfile):
        base = 'deps/chromium/src'
        cmd = f'./{base}/out/Default/quic_server '\
              f'--certificate_file={self.certfile} '\
              f'--key_file={self.keyfile} '\
              f'--num_cached_bytes={self.data_size}'

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
              f'https://www.example.org/{self.data_size} '

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

    def run(
        self, label, logdir, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:
        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = HTTPBenchmarkResult(
                label=label,
                protocol=Protocol.GOOGLE_QUIC.name,
                data_size=self.data_size,
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
        return result


class TCPBenchmark(HTTPDownloadBenchmark):
    def __init__(
        self,
        net: EmulatedNetwork,
        data_size: int,
        cca: str,
        pep: bool,
        certfile: str,
        keyfile: str,
    ):
        """
        TCP file download benchmark using a simple Python server and client.

        Parameters:
        - net: The mininet network.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm. Options include: cubic, reno,
          bbr1, bbr2, bbr3. (Kernel must be the correct version for bbr2 and
          bbr3, which we don't currently check.)
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        """
        super().__init__(
            net=net, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile,
        )
        net.set_tcp_congestion_control(cca)

        self.pep = pep
        self.server_ip = self.net.h2.IP()

    def start_server(self, logfile):
        cmd = f'python3 webserver/http_server.py --server-ip {self.server_ip} '\
              f'--certfile {self.certfile} --keyfile {self.keyfile} '\
              f'-n {self.data_size}'

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
              f'-n {self.data_size}'

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

    def run(
        self, label, logdir, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:
        # Start the server
        self.start_server(logfile=f'{logdir}/{SERVER_LOGFILE}')

        # Start the TCP PEP
        if self.pep:
            self.net.start_tcp_pep(logfile=f'{logdir}/{ROUTER_LOGFILE}')

        # Initialize remaining trials
        num_trials_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = HTTPBenchmarkResult(
                label=label,
                protocol=Protocol.TCP.name,
                data_size=self.data_size,
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
        return result
