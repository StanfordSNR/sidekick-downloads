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


class ProxyType(Enum):
    PEPSAL = 0
    SIDEKICK = 1


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

    @abstractmethod
    def start_server(self, timeout: int=SETUP_TIMEOUT):
        """Start the HTTP server on the h2 host.

        This function runs the server in the background but blocks until the
        server is ready to accept requests. Raises an error if unsuccessful.

        Parameters:
        - timeout: The number of seconds to block during setup before an error.
        """
        pass

    def start_proxy(self, timeout: int=SETUP_TIMEOUT):
        """Starts the proxy on the p1 host, if configured.

        This function runs the proxy in the background but blocks until the
        proxy is ready to serve connections. Raises an error if unsuccessful.

        Parameters:
        - timeout: The number of seconds to block during setup before an error.
        """
        assert self.proxy_type is None

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
        self.start_proxy()

        # Initialize the benchmark result
        result = HTTPBenchmarkResult(
            label=self.label,
            protocol=self.protocol.name,
            data_size=self.data_size,
            cca=self.cca,
            pep=self.proxy_type == ProxyType.PEPSAL,
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
            status_code, time_s = output
            result.set_success(status_code == HTTP_OK_STATUSCODE)
            result.set_timeout(status_code == HTTP_TIMEOUT_STATUSCODE)
            result.set_time_s(time_s)

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
        port: int=4433,
        sidekick: bool=False,
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
        - port: The port to start the HTTP server on.
        - sidekick: Whether to start Sidekick PEP on the p1 host.
        """
        self.port = port
        proxy_type = ProxyType.SIDEKICK if sidekick else None
        super().__init__(
            protocol=Protocol.PICOQUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
            proxy_type=proxy_type
        )
        self.sidekick = sidekick


    def restart_server(self, timeout: int=SETUP_TIMEOUT):
        WARN('Restarting picoquic-server')
        self.server.cmd('killall picoquic_sample')
        self.start_server(timeout=timeout)

    def start_server(self, timeout: int=SETUP_TIMEOUT):
        base = 'deps/picoquic'
        cmd = f'./{base}/picoquic_sample '\
              f'server '\
              f'{self.port} '\
              f'{self.certfile} '\
              f'{self.keyfile} '\
              f'. '\
              f'{self.data_size} '\
              f'{self.cca}'

        DEBUG(f'{self.server.name} {cmd}')
        self.server.cmd(cmd + ' &')
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
        self.net.popen(self.server, cmd, background=True,
            console_logger=DEBUG, logfile=logfile, func=notify_when_ready)
        with condition:
            notified = condition.wait(timeout=timeout)
            if not notified:
                WARN("Server did not print expected output; continuing anyway")
                # raise TimeoutError(f'start_server timeout {timeout}s')
        '''

    def start_proxy(self, timeout=SETUP_TIMEOUT):
        if self.proxy_type == ProxyType.SIDEKICK:
            logfile = self.logfile(self.proxy)
            self.net.start_sidekick(logfile=logfile, timeout=timeout)

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
        base = 'deps/picoquic'
        cmd = f'./{base}/picoquic_sample '\
              f'client '\
              f'{self.server.IP()} '\
              f'{self.port} '\
              f'/tmp '\
              f'{self.cca} '\
              f'{self.data_size}.html '
        if timeout is None:
            DEBUG(f'{self.client.name} {cmd}')
            output = self.client.cmd(cmd)
        else:
            DEBUG(f'{self.client.name} timeout {timeout} {cmd}')
            output = self.client.cmd(f"timeout {timeout} {cmd}")

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
        # timeout_flag = self.net.popen(self.client, cmd, background=False,
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
        sidekick: bool=False,
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
        - sidekick: Whether to start Sidekick PEP on the p1 host.
        """
        self.port = port
        proxy_type = ProxyType.SIDEKICK if sidekick else None
        super().__init__(
            protocol=Protocol.CLOUDFLARE_QUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
            proxy_type=proxy_type
        )
        self.sidekick = sidekick

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
              f'--listen {self.server.IP()}:{self.port}'

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

    def start_proxy(self, timeout=SETUP_TIMEOUT):
        if self.proxy_type == ProxyType.SIDEKICK:
            logfile = self.logfile(self.proxy)
            self.net.start_sidekick(logfile=logfile, timeout=timeout)

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
              f'-- https://{self.server.IP()}:{self.port}/{self.data_size}'

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
            return (HTTP_TIMEOUT_STATUSCODE, timeout)
        elif len(result) == 0:
            WARN('Cloudflare QUIC client failed to return result')
        elif len(result) > 1:
            WARN(f'Cloudflare QUIC client returned multiple results {result}')
        else:
            return (HTTP_OK_STATUSCODE, result[0])


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
        sidekick: bool=False,
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
        - sidekick: Whether to start Sidekick PEP on the p1 host.
        """
        proxy_type = ProxyType.SIDEKICK if sidekick else None
        super().__init__(
            protocol=Protocol.GOOGLE_QUIC,
            net=net, label=label, data_size=data_size, cca=cca,
            certfile=certfile, keyfile=keyfile, logdir=logdir,
            proxy_type=proxy_type
        )
        self.sidekick = sidekick

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

    def start_proxy(self, timeout=SETUP_TIMEOUT):
        if self.proxy_type == ProxyType.SIDEKICK:
            logfile = self.logfile(self.proxy)
            self.net.start_sidekick(logfile=logfile, timeout=timeout)

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
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
                result.append((status_code, time_s))
            except:
                pass

        logfile = self.logfile(self.client)
        timeout_flag = self.net.popen(self.client, cmd, background=False,
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
        pep: bool=False,
        sidekick: bool=False,
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
        - pep: Whether to start a TCP PEP (pepsal) on the p1 host.
        - sidekick: Whether to start Sidekick PEP on the p1 host.
        """
        proxy_type = ProxyType.PEPSAL if pep else ProxyType.SIDEKICK if sidekick else None
        super().__init__(
            protocol=Protocol.TCP,
            net=net, label=label, data_size=data_size, cca=cca, logdir=logdir,
            certfile=certfile, keyfile=keyfile, proxy_type=proxy_type,
        )
        net.set_tcp_congestion_control(cca)

        self.pep = pep
        self.sidekick = sidekick

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

    def start_proxy(self, timeout=SETUP_TIMEOUT):
        logfile = self.logfile(self.proxy)
        if self.proxy_type == ProxyType.PEPSAL:
            self.net.start_tcp_pep(logfile=logfile, timeout=timeout)
        elif self.proxy_type == ProxyType.SIDEKICK:
            self.net.start_sidekick(logfile=logfile, timeout=timeout)

    def run_client(
        self, timeout: Optional[int]=None,
    ) -> Optional[Tuple[int, float]]:
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
                result.append((status_code, time_s))
            except:
                pass

        logfile = self.logfile(self.client)
        timeout_flag = self.net.popen(self.client, cmd, background=False,
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
