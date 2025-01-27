import json

from .result import HTTPBenchmarkResult


# \NOTE using `popen` on the network as in the other benchmarks
# did not reliably work for some older kernel versions, so we use
# hX.cmd(XX) for this benchmark instead.
class Iperf3Benchmark:
    def __init__(
        self,
        net,
        n: int,
        cca: str,
        pep: bool,
        sidekick: bool,
    ):
        self.net = net
        self.n = n
        self.pep = pep
        self.sidekick = sidekick
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
        elif self.sidekick:
            self.net.start_sidekick()
        num_trials_left = num_trials

        while num_trials_left > 0:

            result = HTTPBenchmarkResult(
                label=label,
                protocol='TCP_IPERF3',
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

            print(result.json())

        self.stop_server()
