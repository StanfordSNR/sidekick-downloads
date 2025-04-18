import time
import threading
from typing import Optional, List
from dataclasses import dataclass
import re
import json
import multiprocessing

import mininet

from common import *
from network import MulticastNetwork
from .result import MulticastBenchmarkResult


@dataclass(frozen=True)
class MulticastClientOutput:
    time_s: int
    client_ids: List[str]
    latencies: List[List[int]]
    num_spurious: List[int]
    additional_data: any = None


class MulticastBenchmark:
    def __init__(
        self,
        net: MulticastNetwork,
        label: str,
        duration: int,
        frequency: int,
        logdir: str,
        num_clients: int,
        num_quackers: int=0,
        quacker: Optional[QuackerConfig]=None,
        port: int=5201,
        nack_delay: int=0,
        proxy_type: Optional[ProxyType]=None,
    ):
        """
        Multicast benchmark where the client on h1 initiates a bidirectional stream
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
        - duration: The length of the client stream, in seconds.
        - frequency: The frequency at which the server sends data packets,
          in ms. The payload size is 240 bytes.
        - num_clients: Number of multicast clients in the group.

        Optional parameters:
        - num_quackers: The number of quackers. Must be at most the number of
          clients. (default: 0)
        - quacker: If enabled, the quacker configuration.
        - port: The port to start the multicast server on (default: 5201).
        - nack_delay: Delay (ms) of the NACK signal to reduce spurious retxes.
        - proxy_type: The type of proxy on the p1 host, if any.
        """
        self.net = net
        self.label = label
        self.duration = duration
        self.port = port
        self.frequency = frequency
        self.proxy_type = 'none' if proxy_type is None else proxy_type.value
        self._logdir = logdir
        self.nack_delay = nack_delay
        self.num_clients = num_clients
        self.num_quackers = num_quackers
        self.quacker = quacker
        self.client_ids = {}
        for i, client in enumerate(self.clients):
            self.client_ids[client] = i + 1

    @property
    def clients(self) -> List[mininet.node.Host]:
        """The mininet hosts of the Multicast clients.
        """
        return self.net.clients

    @property
    def server(self) -> mininet.node.Host:
        """The mininet host of the Multicast server.
        """
        return self.net.server

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
        elif host in self.clients:
            client_id = self.client_ids[host]
            return f'{self._logdir}/{CLIENT_LOGFILE}.{client_id}'
        elif host == self.proxy and self.proxy is not None:
            return f'{self._logdir}/{ROUTER_LOGFILE}'

    def start_server(self, timeout: int=SETUP_TIMEOUT):
        """Start the media server on the h2 host and write output to a logfile.

        This function runs the server in the background but blocks until the
        server is ready to accept requests. Raises an error if unsuccessful.

        Parameters:
        - timeout: The number of seconds to block during setup before an error.
        """
        cmd = f'./media/target/release/multicast_server '\
              f'--frequency {self.frequency} '\
              f'--port {self.port} '

        condition = threading.Condition()
        def parse_output(line):
            # The server needs to notify the active process when it is ready to
            # serve requests.
            if 'Ready to accept' in line:
                with condition:
                    condition.notify()
                return

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

    def run_client(self) -> Optional[MulticastClientOutput]:
        """
        Runs the Multicast client on the h1 host and writes output to a logfile.
        """
        cmd = f'./media/target/release/multicast_client '\
              f'--nack-frequency {self.net.rtt} '\
              f'--frequency {self.frequency} '\
              f'--addr {self.server.IP()}:{self.port} '\
              f'--timeout {self.duration} '

        # Create a thread-safe and process-safe results object
        manager = multiprocessing.Manager()
        results = manager.dict()
        lock = manager.Lock()
        def parse_result(line):
            match1 = re.search(r'\[(ID\d+)\] Num Spurious: (\d+)', line)
            match2 = re.search(r'\[(ID\d+)\] Raw values = (\[.*\])', line)
            if match1:
                client_id = str(match1.group(1))
                key = 'num_spurious'
                val = int(match1.group(2))
            elif match2:
                client_id = str(match2.group(1))
                key = 'latencies'
                val = json.loads(match2.group(2))
            else:
                return
            with lock:
                if client_id not in results:
                    results[client_id] = manager.dict()
                results[client_id][key] = val

        # Run all the clients simultaneously
        start = time.time()
        processes = []
        threads = []
        quackers_remaining = self.num_quackers
        for host in self.clients:
            logfile = self.logfile(host)
            client_cmd = f'{cmd} --client-id {self.client_ids[host]} '
            if quackers_remaining > 0:
                q = self.quacker
                target_addr = f'{self.proxy.IP()}:{q.quackee_port}'
                # Only clients using the quacker use the nack delay feature
                client_cmd += f'--nack-delay {self.nack_delay} '
                client_cmd += f'--quacker '\
                              f'--threshold {q.threshold} '\
                              f'--frequency-pkts {q.freq_pkts} '\
                              f'--frequency-ms {q.freq_ms} '\
                              f'--target-addr {target_addr} '
                if q.riblt:
                    client_cmd += '--riblt '
                if q.hint:
                    client_cmd += '--hint '
                if q.send_on_nack:
                    client_cmd += '--send-on-nack '
                quackers_remaining -= 1
            p, thread = self.net.popen(host, client_cmd,
                background=True, console_logger=DEBUG, logfile=logfile,
                func=parse_result, raise_error=False)
            processes.append(p)
            threads.append(thread)

        # Wait until they are complete, up to 2x the expected duration, after
        # which there is probably an error and we timeout
        timeout_time = start + 2 * self.duration
        for p, thread in zip(processes, threads):
            remaining_time = max(0, timeout_time - time.time())
            try:
                p.wait(timeout=remaining_time)
            except subprocess.TimeoutExpired:
                p.terminate()
                return None
            thread.join()
        end = time.time()

        # Set the multicast client output
        with lock:
            client_ids = list(sorted(results.keys()))
            latencies = [results[cid]['latencies'] for cid in client_ids]
            num_spurious = [results[cid]['num_spurious'] for cid in client_ids]
        output = MulticastClientOutput(
            time_s=end - start, client_ids=client_ids, latencies=latencies,
            num_spurious=num_spurious,
        )
        return output

    def run_benchmark(
        self, num_trials: int, network_statistics: bool=False,
    ) -> MulticastBenchmarkResult:
        """
        Running the benchmark will start the Multicast server on the h2 host and
        the Multicast client on the h1 host, the latter as many times as the number
        of trials. If there is an error that is not a timeout, try restarting
        the server. If a proxy is configured, running the benchmark will also
        start the proxy on the p1 host.

        Parameters:
        - num_trials: Number of trials.
        - network_statistics: Whether to collect network statistics, i.e., the
          number of bytes and packets that were sent and received at each
          interface, of the most recent trial.

        Returns:
        - A MulticastBenchmarkResult corresponding to the result of this benchmark.
        """
        self.start_server()

        # Initialize the benchmark result
        result = MulticastBenchmarkResult(
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
                result.set_timeout(True)
                continue

            # Handle a successful trial
            result.set_success(True)
            result.set_time_s(output.time_s)
            result.set_client_ids(output.client_ids)
            result.set_latencies(output.latencies)
            result.set_num_spurious(output.num_spurious)
            if output.additional_data is not None:
                result.set_additional_data(output.additional_data)

        # Return the result
        return result
