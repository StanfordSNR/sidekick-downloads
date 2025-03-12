import time
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass
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


@dataclass(frozen=True)
class HTTPClientOutput:
    status_code: int
    time_s: int
    additional_data: Optional[dict] = None


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
        server_port: int,
        proxy_type: Optional[ProxyType]=None,
    ):
        """
        File download benchmark where the HTTP client on the h1 host requests
        a certain number of application-layer bytes from the HTTP server on
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
        - proxy_type: The type of proxy to start on the p1 host, if any.
        """
        self.net = net
        self._label = label
        self._protocol = protocol
        self._data_size = data_size
        self._cca = cca
        self._certfile = certfile
        self._keyfile = keyfile
        self._logdir = logdir
        self._proxy_type = proxy_type
        self._server_port = server_port

    @property
    def client(self) -> mininet.node.Host:
        """The mininet host of the HTTP client.
        """
        return self.net.h1

    @property
    def server(self) -> mininet.node.Host:
        """The mininet host of the HTTP server.
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

    @property
    def proxy_type(self) -> Optional[ProxyType]:
        """The type of proxy to start on the p1 host, if any.
        """
        return self._proxy_type

    @property
    def server_port(self) -> int:
        """The port that the server is listening on.
        """
        return self._server_port

    @abstractmethod
    def start_server(self, timeout: int=SETUP_TIMEOUT):
        """Start the HTTP server on the h2 host and write output to a logfile.

        This function runs the server in the background but blocks until the
        server is ready to accept requests. Raises an error if unsuccessful.

        Parameters:
        - timeout: The number of seconds to block during setup before an error.
        """
        pass

    @abstractmethod
    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[HTTPClientOutput]:
        """
        Runs the HTTP client on the h1 host and writes output to a logfile.

        Parameters:
        - timeout: If provided, the number of seconds to wait for the client
          to complete its request.

        Returns:
        - If there is an error that is not a timeout, returns None.
        - The HTTP status code and the total runtime, in seconds, of the GET
          request, along with other optional statistics. If the client has
          timed out, returns HTTP_TIMEOUT_STATUSCODE even though the timeout
          may not have occurred in the actual endpoints.
        """
        pass

    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        """If implemented, kills the existing server and restarts it.
        """
        pass

    def run_benchmark(
        self, num_trials: int, timeout: Optional[int]=None,
        network_statistics: bool=False,
    ) -> HTTPBenchmarkResult:
        """
        Running the benchmark will start the HTTP server on the h2 host and
        the HTTP client on the h1 host, the latter as many times as the number
        of trials. If there is an error that is not a timeout, try restarting
        the server. If a proxy is configured, running the benchmark will also
        start the proxy on the p1 host.

        Parameters:
        - num_trials: Number of trials.
        - timeout: If provided, the number of seconds to wait for each client
          to complete its request.
        - network_statistics: Whether to collect network statistics, i.e., the
          number of bytes and packets that were sent and received at each
          interface, of the most recent trial.

        Returns:
        - A HTTPBenchmarkResult corresponding to the result of this benchmark.
        """
        self.start_server()

        if self.proxy_type == ProxyType.PICOQUIC:
            self.net.start_picoquic_splitter(PROXY_PORT, self.certfile, self.keyfile, self.cca,
                                            self.server_port, self.server.IP(),
                                            logfile=self.logfile(self.proxy))
        print(f"Start benchmark: server {self.server.IP()}:{self.server_port}, client {self.client.IP()}, " \
              f"proxy {self.proxy.IP() if self.proxy is not None else 'none'}")

        # Initialize the benchmark result
        result = HTTPBenchmarkResult(
            label=self.label,
            protocol=self.protocol.name,
            data_size=self.data_size,
            cca=self.cca,
            proxy_type='none' if self.proxy_type is None else self.proxy_type.value,
        )

        # Run the client
        for _ in range(num_trials):
            result.append_new_output()
            self.net.reset_statistics()
            output = self.run_client(timeout=timeout)
            if network_statistics:
                statistics = self.net.snapshot_statistics()
                result.set_network_statistics(statistics)

            # Handle an error in the client
            if output is None:
                result.set_success(False)
                result.set_timeout(False)
                self.restart_server()
                continue

            # Handle a successful trial
            result.set_success(output.status_code == HTTP_OK_STATUSCODE)
            result.set_timeout(output.status_code == HTTP_TIMEOUT_STATUSCODE)
            result.set_time_s(output.time_s)
            if output.additional_data is not None:
                result.set_additional_data(output.additional_data)

        # Return the result
        return result


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
        quacker: Optional[QuackerConfig]=None,
        ack_delay: int=0,
        port: int=4433,
        proxy_type: Optional[ProxyType]=None,
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

        Optional parameters:
        - quacker: If enabled, the quacker configuration.
        - ack_delay: Delay (ms) of sidekick ACK signal to reduce spurious retx
          (default: 0).
        - port: The port to start the HTTP server on (default: 5252).
        - proxy: The type of network proxy (default: None).
        """
        self.ack_delay = ack_delay
        self.quacker = quacker
        super().__init__(
            protocol=Protocol.PICOQUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
            server_port=port,
            proxy_type=proxy_type
        )

        # Fields for the server to notify the client of certain statistics
        self.condition = threading.Condition()
        self.additional_data = {}

    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        WARN('Restarting picoquic-server')
        self.server.cmd('killall picoquic_sample')
        self.start_server(timeout=timeout)

    def start_server(self, timeout: int=SETUP_TIMEOUT):
        base = 'deps/picoquic'
        cmd = f'./{base}/picoquic_sample '\
              f'server '\
              f'{self.server_port} '\
              f'{self.certfile} '\
              f'{self.keyfile} '\
              f'. '\
              f'{self.data_size} '\
              f'{self.cca}'


        condition = threading.Condition()
        def parse_output(line):
            # The server needs to parse output for two purposes:
            # 1) Notify the active process when it is ready to serve requests.
            if line.startswith('Serving'):
                with condition:
                    condition.notify()
                return
            # 2) On request completion, log the number of spurious retxs.
            pattern = r'Finished file transfer.*(?P<spurious>\d+) spurious'
            match = re.search(pattern, line)
            if match is not None:
                with self.condition:
                    num_spurious = int(match.group(1))
                    self.additional_data['num_spurious_sender'] = num_spurious
                    self.condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        logfile = self.logfile(self.server)
        self.net.popen(self.server, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=parse_output)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[HTTPClientOutput]:
        target_ip = self.server.IP() if self.proxy_type != ProxyType.PICOQUIC else self.proxy.IP()
        target_port = self.server_port if self.proxy_type != ProxyType.PICOQUIC else PROXY_PORT
        base = 'deps/picoquic'
        cmd = f'./{base}/picoquic_sample '\
              f'client '\
              f'{target_ip} '\
              f'{target_port} '\
              f'/tmp '\
              f'{self.cca} '\
              f'{self.ack_delay} '

        # Add parameters to configure the client quacker
        if self.quacker is not None:
            q = self.quacker
            assert not q.hint  # not implemented
            target_addr = f'{self.proxy.IP()}:{q.quackee_port}'
            cmd += f'{q.threshold} {q.freq_pkts} {q.freq_ms} {target_addr} '
            cmd += f'{int(q.riblt)} {int(q.hint)} '

        # Add the data size parameter
        cmd += f'{self.data_size}.html '

        result = []
        def parse_result(line):
            pattern = r'complete.*in ([\d.]+) seconds, (\d+) spurious'
            match = re.search(pattern, line)
            if match is None:
                return
            time_s = float(match.group(1))
            result.append(time_s)
            self.additional_data['num_spurious_receiver'] = int(match.group(2))

        with self.condition:
            logfile = self.logfile(self.client)
            timeout_flag = self.net.popen(self.client, cmd, background=False,
                console_logger=DEBUG, logfile=logfile, func=parse_result,
                timeout=timeout, raise_error=False)

            # Check for an error running the client
            if len(result) == 0:
                WARN('PicoQUIC client failed to return result')
            elif len(result) > 1:
                WARN(f'PicoQUIC client returned multiple results {result}')
            elif timeout_flag:
                return HTTPClientOutput(HTTP_TIMEOUT_STATUSCODE, timeout)

            # Wait for the server to log the number of spurious retransmissions.
            if not self.condition.wait(timeout=5):
                raise TimeoutError(f'timeout waiting for server stats')
            return HTTPClientOutput(HTTP_OK_STATUSCODE, result[0], self.additional_data)


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
        port: int=4433,
        proxy_type: Optional[ProxyType]=None,
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
        - port: The port to start the HTTP server on.
        - proxy: The type of network proxy.
        """
        super().__init__(
            protocol=Protocol.CLOUDFLARE_QUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
            server_port=port,
            proxy_type=proxy_type
        )

    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        WARN('Restarting quiche-server')
        self.server.cmd('killall quiche-server')
        self.start_server(timeout=timeout)

    def start_server(self, timeout: int=SETUP_TIMEOUT):
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

        base = 'deps/quiche/target/release'
        cmd = f'./{base}/quiche-server '\
              f'--cert={self.certfile} '\
              f'--key={self.keyfile} '\
              f'--cc-algorithm {self.cca} ' \
              f'--listen {self.server.IP()}:{self.server_port}'

        condition = threading.Condition()
        def notify_when_ready(line):
            if 'listening' in line.lower():
                with condition:
                    condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        logfile = self.logfile(self.server)
        self.net.popen(self.server, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[HTTPClientOutput]:
        # Required outputs are in INFO logs
        os.environ['RUST_LOG'] = 'info'

        base = 'deps/quiche/target/release'
        cmd = f'./{base}/quiche-client '\
              f'--no-verify '\
              f'--method GET '\
              f'--cc-algorithm {self.cca} ' \
              f'-- https://{self.server.IP()}:{self.server_port}/{self.data_size}'

        result = []
        timed_out = False
        def parse_result(line):
            if 'response(s) received in ' not in line:
                return
            if 'Not found' in line:
                return
            if 'timed out' in line:
                timed_out = True
            else:
                match = re.search(r'received in \d+\.\d+s', line)
                if not match:
                    match = re.search(r'received in \d+\.\d+ms', line)
                    if not match:
                        raise Exception(f'Could not get time from string {line}')
                    match = match.group(0)
                    time_s = float(match.split(' ')[-1].replace('ms', '')) / 1000
                else:
                    match = match.group(0)
                    time_s = float(match.split(' ')[-1].replace('s', ''))
                result.append(time_s)

        logfile = self.logfile(self.client)
        timeout_flag = self.net.popen(self.client, cmd, background=False,
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
            return HTTPClientOutput(HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            WARN('Cloudflare QUIC client failed to return result')
        elif len(result) > 1:
            WARN(f'Cloudflare QUIC client returned multiple results {result}')
        else:
            return HTTPClientOutput(HTTP_OK_STATUSCODE, result[0])


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
        proxy_type: Optional[ProxyType]=None,
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
        - proxy: The type of network proxy.
        """
        super().__init__(
            protocol=Protocol.GOOGLE_QUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
            server_port=0, # N/A
            proxy_type=proxy_type
        )

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
        self.net.popen(self.server, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[HTTPClientOutput]:
        base = 'deps/chromium/src'
        cmd = f'./{base}/out/Default/quic_client '\
              f'--allow_unknown_root_cert '\
              f'--host={self.server.IP()} --port=6121 '\
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
                result.append(HTTPClientOutput(status_code, time_s))
            except:
                pass

        logfile = self.logfile(self.client)
        timeout_flag = self.net.popen(self.client, cmd, background=False,
            console_logger=DEBUG, logfile=logfile, func=parse_result,
            timeout=timeout)
        if timeout_flag:
            return HTTPClientOutput(HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            # E.g., 404 not found
            WARN('QUIC client failed to return result')
        elif len(result) > 1:
            WARN(f'QUIC client returned multiple results {result}')
        else:
            return result[0]


class TCPBenchmark(HTTPDownloadBenchmark):
    def __init__(
        self,
        net: EmulatedNetwork,
        label: str,
        data_size: int,
        cca: str,
        certfile: str,
        keyfile: str,
        logdir: str,
        proxy_type: Optional[ProxyType]=None,
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
        - proxy: The type of network proxy.
        """
        super().__init__(
            protocol=Protocol.TCP,
            net=net, label=label, data_size=data_size, cca=cca, logdir=logdir,
            certfile=certfile, keyfile=keyfile, server_port=8443,
            proxy_type=proxy_type,
        )
        net.set_tcp_congestion_control(cca)

    def start_server(self, timeout: int=SETUP_TIMEOUT):
        cmd = f'python3 webserver/http_server.py '\
              f'--server-ip {self.server.IP()} -n {self.data_size} '\
              f'--certfile {self.certfile} --keyfile {self.keyfile} '

        condition = threading.Condition()
        def notify_when_ready(line):
            if 'Serving' in line:
                with condition:
                    condition.notify()

        # The start_server() function blocks until the server is ready to
        # accept client requests. That is, when we observe the 'Serving'
        # string in the server output.
        logfile = self.logfile(self.server)
        self.net.popen(self.server, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                raise TimeoutError(f'start_server timeout {timeout}s')

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[HTTPClientOutput]:
        cmd = f'python3 webserver/http_client.py '\
              f'--server-ip {self.server.IP()} -n {self.data_size}'

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
                result.append(HTTPClientOutput(status_code, time_s))
            except:
                pass

        logfile = self.logfile(self.client)
        timeout_flag = self.net.popen(self.client, cmd, background=False,
            console_logger=DEBUG, logfile=logfile, func=parse_result,
            timeout=timeout)
        if timeout_flag:
            return HTTPClientOutput(HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            WARN('TCP client failed to return result')
        elif len(result) > 1:
            WARN(f'TCP client returned multiple results {result}')
        else:
            return result[0]
