import time
import threading
from abc import ABC, abstractmethod
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
        label: str,
        protocol: Protocol,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
        logdir: str,
    ):
        """
        File download benchmark where the HTTPS client on the h1 host requests
        a certain number of application-layer bytes from the HTTPS server on
        the h2 host. Reports metrics such as the request latency and throughput.

        Subclasses of HTTPDownloadBenchmark must call this constructor.

        Parameters:
        - net: The mininet network to run the benchmark on. Requires an h1 and
          h2 host, and a p1 host if a proxy is configured.
        - label: The unique label to associate with this configuration.
        - protocol: The transport protocol implementation.
        - data_size: The number of application-layer bytes transferred in the
          GET request.
        - cca: The congestion control algorithm used in the transport protocol.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        - logdir: Path to a log directory (that already exists). The logs are
          written to the SERVER_LOGFILE, CLIENT_LOGFILE, and ROUTER_LOGFILE
          files in this directory, as defined in common.py.
        """
        self.net = net
        self._label = label
        self._protocol = protocol
        self._data_size = data_size
        self._cca = cca
        self._certfile = certfile
        self._keyfile = keyfile
        self._logdir = logdir

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
    def proxy(self) -> Optional[mininet.node.Host]:
        """The mininet host of the proxy, if any.
        """
        if not hasattr(self.net, 'p1'):
            return None
        else:
            return self.net.p1

    @property
    def label(self) -> str:
        """The unique label associated with this benchmark configuration.
        """
        return self._label

    @property
    def protocol(self) -> Protocol:
        """The transport protocol implementation used in this benchmark.
        """
        return self._protocol

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

    def logfile(self, host: mininet.node.Host) -> Optional[str]:
        """Path to the logfile for this host. The logs are written to the
        SERVER_LOGFILE, CLIENT_LOGFILE, and ROUTER_LOGFILE files, as defined in
        common.py, in the provided log directory.
        """
        if host == self.server:
            return f'{self._logdir}/{SERVER_LOGFILE}'
        elif host == self.client:
            return f'{self._logdir}/{CLIENT_LOGFILE}'
        elif host == self.proxy and self.proxy is not None:
            return f'{self._logdir}/{ROUTER_LOGFILE}'

    @abstractmethod
    def start_server(self, timeout: int=SETUP_TIMEOUT):
        """Start the HTTPS server on the h2 host.

        This function runs the server in the background but blocks until the
        server is ready to accept requests. Raises an error if unsuccessful.

        Parameters:
        - timeout: The number of seconds to block during setup before an error.
        """
        pass

    @abstractmethod
    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
        """
        Parameters:
        - timeout: If provided, the number of seconds to wait for the client
          to complete its request.

        Returns:
        - If there is an error that is not a timeout, returns None.
        - (http_status_code, total_time): The HTTP status code and the total
          runtime, in seconds, of the GET request. If the client has timed out,
          returns HTTP_TIMEOUT_STATUSCODE even though the timeout may not have
          occurred in the actual endpoints.
        """
        pass

    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        """If implemented, kills the existing server and restarts it.
        """
        pass


class PicoQUICBenchmark(HTTPDownloadBenchmark):
    def __init__(
        self,
        net: EmulatedNetwork,
        label: str,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
        logdir: str,
    ):
        """
        Picoquic file download benchmark.

        Parameters:
        - net: The mininet network.
        - label: A label for the benchmark.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        - logdir: Path to a log directory (that already exists).
        """
        super().__init__(
            protocol=Protocol.PICOQUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
        )
        self.server_ip = self.net.h2.IP()

    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        WARN('Restarting picoquic-server')
        self.net.h2.cmd('killall picoquic_sample')
        self.start_server(timeout=timeout)

    def start_server(self, timeout: int=SETUP_TIMEOUT):
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
            notified = condition.wait(timeout=timeout)
            if not notified:
                WARN("Server did not print expected output; continuing anyway")
                # raise TimeoutError(f'start_server timeout {timeout}s')
        '''

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
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
        self, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:

        # Start the server
        self.start_server()

        # Initialize remaining trials
        num_trials_left = num_trials
        # allow N "no output" errors without decrementing trials
        num_errors_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = HTTPBenchmarkResult(
                label=self.label,
                protocol=self.protocol.name,
                data_size=self.data_size,
                cca=self.cca,
                pep=False,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(timeout=timeout)

                # Error
                if output is None:
                    ERROR('no output')
                    self.restart_server()
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
        label: str,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
        logdir: str,
    ):
        """
        Cloudflare QUIC file download benchmark.

        Parameters:
        - net: The mininet network.
        - label: A label for the benchmark.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        - logdir: Path to a log directory (that already exists).
        """
        super().__init__(
            protocol=Protocol.CLOUDFLARE_QUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
        )
        self.server_ip = self.net.h2.IP()

    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        WARN('Restarting quiche-server')
        self.net.h2.cmd('killall quiche-server')
        self.start_server(timeout=timeout)

    def start_server(self, timeout: int=SETUP_TIMEOUT):
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
        logfile = self.logfile(self.server)
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
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

        logfile = self.logfile(self.client)
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
        self, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

        # Start the server
        self.start_server()

        # Run the client
        result = HTTPBenchmarkResult(
            label=self.label,
            protocol=self.protocol.name,
            data_size=self.data_size,
            cca=self.cca,
            pep=False,
        )

        for _ in range(num_trials):
            result.append_new_output()
            self.net.reset_statistics()
            output = self.run_client(timeout=timeout)

            # Error
            if output is None:
                ERROR('no output')
                self.restart_server()
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
        label: str,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
        logdir: str,
    ):
        """
        Google QUIC file download benchmark.

        Parameters:
        - net: The mininet network.
        - label: A label for the benchmark.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm.
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        - logdir: Path to a log directory (that already exists).
        """
        super().__init__(
            protocol=Protocol.GOOGLE_QUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
        )
        self.server_ip = self.net.h2.IP()

    def start_server(self, timeout: int=SETUP_TIMEOUT):
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
        logfile = self.logfile(self.server)
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
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

        logfile = self.logfile(self.client)
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
        self, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:
        # Start the server
        self.start_server()

        # Initialize remaining trials
        num_trials_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = HTTPBenchmarkResult(
                label=self.label,
                protocol=self.protocol.name,
                data_size=self.data_size,
                cca=self.cca,
                pep=False,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(timeout=timeout)

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
        label: str,
        data_size: int,
        cca: str,
        pep: bool,
        certfile: str,
        keyfile: str,
        logdir: str,
    ):
        """
        TCP file download benchmark using a simple Python server and client.

        Parameters:
        - net: The mininet network.
        - label: A label for the benchmark.
        - data_size: Number of bytes to GET.
        - cca: The congestion control algorithm. Options include: cubic, reno,
          bbr1, bbr2, bbr3. (Kernel must be the correct version for bbr2 and
          bbr3, which we don't currently check.)
        - certfile: Path to the TLS/SSL certificate file.
        - keyfile: Path to the TLS/SSL key file.
        - logdir: Path to a log directory (that already exists).
        """
        super().__init__(
            protocol=Protocol.TCP,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
        )
        net.set_tcp_congestion_control(cca)

        self.pep = pep
        self.server_ip = self.net.h2.IP()

    def start_server(self, timeout: int=SETUP_TIMEOUT):
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
        logfile = self.logfile(self.server)
        self.net.popen(self.net.h2, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
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

        logfile = self.logfile(self.client)
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
        self, num_trials, timeout, network_statistics,
    ) -> HTTPBenchmarkResult:
        # Start the server
        self.start_server()

        # Start the TCP PEP
        if self.pep:
            logfile = self.logfile(self.proxy)
            self.net.start_tcp_pep(logfile=logfile)

        # Initialize remaining trials
        num_trials_left = num_trials

        # Run the client
        while num_trials_left > 0:
            result = HTTPBenchmarkResult(
                label=self.label,
                protocol=self.protocol.name,
                data_size=self.data_size,
                cca=self.cca,
                pep=self.pep,
            )

            # Log output every LOG_CHUNK_TIME while continuing to run trials
            total_time_s = 0
            while num_trials_left > 0 and total_time_s < LOG_CHUNK_TIME:
                result.append_new_output()
                self.net.reset_statistics()
                output = self.run_client(timeout=timeout)

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
