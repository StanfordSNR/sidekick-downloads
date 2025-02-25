import time
import threading
from typing import Optional, List
from dataclasses import dataclass
import re
import json

import mininet

from common import *
from network import EmulatedNetwork
from .result import MediaBenchmarkResult


@dataclass(frozen=True)
class MediaClientOutput:
    time_s: int
    client_latencies: List[int]
    server_latencies: List[int]
    client_num_spurious: int
    additional_data: any = None


class MediaBenchmark:
    def __init__(
        self,
        net: EmulatedNetwork,
        label: str,
        duration: int,
        frequency: int,
        logdir: str,
        quacker: Optional[QuackerConfig]=None,
        ack_delay: int=0,
        proxy_type: Optional[ProxyType]=None,
    ):
        """
        Media benchmark where the client on h1 initiates a bidirectional stream
        of data with the server on h2 for a specified duration. The client also
        ends the connection. Reports the raw dejitter buffer delays for each
        packet, as well as metrics such as the p95 and p99 delay.

        Parameters:
        - net: The mininet network to run the benchmark on. Requires an h1 and
          h2 host, and a p1 host if a proxy is configured.
        - label: The unique label to associate with this configuration.
        - logdir: Path to a log directory (that already exists). The logs are
          written to the SERVER_LOGFILE, CLIENT_LOGFILE, and ROUTER_LOGFILE
          files in this directory, as defined in common.py.
        - duration: The length of the stream, in seconds.
        - frequency: The frequency at which to send data packets, in ms. The
          payload size is 240 bytes.

        Optional parameters:
        - quacker: If enabled, the quacker configuration.
        - ack_delay: Delay (ms) of the NACK signal to reduce spurious retxes.
        - proxy_type: The type of proxy on the p1 host, if any.
        """
        self.net = net
        self.label = label
        self.duration = duration
        self.frequency = frequency
        self.proxy_type = 'none' if proxy_type is None else proxy_type.value
        self._logdir = logdir
        self.nack_delay = ack_delay
        self.quacker = quacker

        # Fields for the server to notify the client of certain statistics
        self.condition = threading.Condition()
        self.additional_data = None

    @property
    def client(self) -> mininet.node.Host:
        """The mininet host of the Media client.
        """
        return self.net.h1

    @property
    def server(self) -> mininet.node.Host:
        """The mininet host of the Media server.
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

    def start_server(self, timeout: int=SETUP_TIMEOUT):
        """Start the media server on the h2 host and write output to a logfile.

        This function runs the server in the background but blocks until the
        server is ready to accept requests. Raises an error if unsuccessful.

        Parameters:
        - timeout: The number of seconds to block during setup before an error.
        """
        cmd = f'./media/target/release/endpoint '\
              f'--nack-frequency {self.net.rtt} '\
              f'--frequency {self.frequency} '\
              f'server '

        condition = threading.Condition()
        def parse_output(line):
            # The server needs to parse output for two purposes:
            # 1) Notify the active process when it is ready to serve requests.
            if 'Ready to accept' in line:
                with condition:
                    condition.notify()
                return
            # 2) On request completion, log the raw dejitter latencies.
            pattern = r'Raw values = (\[.*\])'
            match = re.search(pattern, line)
            if match is not None:
                with self.condition:
                    latencies = json.loads(match.group(1))
                    self.additional_data = latencies
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

    def run_client(self) -> Optional[MediaClientOutput]:
        """
        Runs the Media client on the h1 host and writes output to a logfile.
        """
        cmd = f'./media/target/release/endpoint '\
              f'--nack-frequency {self.net.rtt} '\
              f'--nack-delay {self.nack_delay} '\
              f'--frequency {self.frequency} '

        # Add parameters to configure the client quacker
        if self.quacker is not None:
            q = self.quacker
            target_addr = f'{self.proxy.IP()}:{q.quackee_port}'
            cmd += f'--quacker '\
                   f'--threshold {q.threshold} '\
                   f'--frequency-pkts {q.freq_pkts} '\
                   f'--frequency-ms {q.freq_ms} '\
                   f'--target-addr {target_addr} '

        # Add client parameters
        cmd += f'client --timeout {self.duration} '

        result = {}
        def parse_result(line):
            match1 = re.search(r'Num Spurious: (\d+)', line)
            match2 = re.search(r'Raw values = (\[.*\])', line)
            if match1:
                result['num_spurious'] = int(match1.group(1))
            elif match2:
                result['latencies'] = json.loads(match2.group(1))

        with self.condition:
            logfile = self.logfile(self.client)
            start = time.time()
            self.net.popen(self.client, cmd, background=False,
                console_logger=DEBUG, logfile=logfile, func=parse_result,
                raise_error=False)
            end = time.time()

            # Check for an error running the client
            if 'num_spurious' not in result or 'latencies' not in result:
                WARN('Media client failed to return result')

            # Wait for the server to log its dejitter latencies.
            if not self.condition.wait(timeout=5):
                raise TimeoutError(f'timeout waiting for server stats')
            return MediaClientOutput(
                time_s=end - start,
                client_latencies=result.get('latencies'),
                server_latencies=self.additional_data,
                client_num_spurious=result.get('num_spurious'),
            )

    def run_benchmark(
        self, num_trials: int, timeout: Optional[int]=None,
        network_statistics: bool=False,
    ) -> MediaBenchmarkResult:
        """
        Running the benchmark will start the Media server on the h2 host and
        the Media client on the h1 host, the latter as many times as the number
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
        - A MediaBenchmarkResult corresponding to the result of this benchmark.
        """
        self.start_server()

        # Initialize the benchmark result
        result = MediaBenchmarkResult(
            label=self.label,
            proxy_type=self.proxy_type,
        )

        # Run the client
        for _ in range(num_trials):
            result.append_new_output()
            self.net.reset_statistics()
            output = self.run_client()
            if network_statistics:
                statistics = self.net.snapshot_statistics()
                result.set_network_statistics(statistics)

            # Handle an error in the client
            if output is None:
                result.set_success(False)
                continue

            # Handle a successful trial
            result.set_success(True)
            result.set_time_s(output.time_s)
            result.set_client_latencies(output.client_latencies)
            result.set_server_latencies(output.server_latencies)
            result.set_client_num_spurious(output.client_num_spurious)
            if output.additional_data is not None:
                result.set_additional_data(output.additional_data)

        # Return the result
        return result
