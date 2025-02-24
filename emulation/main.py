import argparse
import sys
import time
from common import *
from network import *
from benchmark import *
from mininet.cli import CLI
from mininet.log import setLogLevel


DEFAULT_SSL_CERTFILE = f'deps/certs/out/leaf_cert.pem'
DEFAULT_SSL_KEYFILE_QUIC = f'deps/certs/out/leaf_cert.pkcs8'
DEFAULT_SSL_KEYFILE_TCP = f'deps/certs/out/leaf_cert.key'


def benchmark_tcp(net, args):
    bm = TCPBenchmark(
        net,
        label=args.label,
        data_size=args.n,
        cca=args.congestion_control,
        certfile=args.certfile,
        keyfile=args.keyfile,
        logdir=args.logdir,
        proxy_type=args.proxy,
    )
    result = bm.run_benchmark(
        args.trials,
        args.timeout,
        args.network_statistics,
    )
    print(result.json())


def benchmark_google_quic(net, args):
    bm = GoogleQUICBenchmark(
        net,
        label=args.label,
        data_size=args.n,
        cca=args.congestion_control,
        certfile=args.certfile,
        keyfile=args.keyfile,
        logdir=args.logdir,
        proxy_type=args.proxy,
    )
    result = bm.run_benchmark(
        args.trials,
        args.timeout,
        args.network_statistics,
    )
    print(result.json())


def benchmark_cloudflare_quic(net, args):
    bm = CloudflareQUICBenchmark(
        net,
        label=args.label,
        data_size=args.n,
        cca=args.congestion_control,
        certfile=args.certfile,
        keyfile=args.keyfile,
        logdir=args.logdir,
        proxy_type=args.proxy,
    )
    result = bm.run_benchmark(
        args.trials,
        args.timeout,
        args.network_statistics,
    )
    print(result.json())


def benchmark_picoquic(net, args):
    # Generate the config for the client quacker, if enabled
    if args.client_quacker:
        quacker = QuackerConfig.from_args(args)
    else:
        quacker = None

    # Create the benchmark and run it
    bm = PicoQUICBenchmark(
        net,
        label=args.label,
        data_size=args.n,
        cca=args.congestion_control,
        certfile=args.certfile,
        keyfile=args.keyfile,
        logdir=args.logdir,
        ack_delay=args.ack_delay,
        quacker=quacker,
        proxy_type=args.proxy,
    )
    result = bm.run_benchmark(
        args.trials,
        args.timeout,
        args.network_statistics,
    )
    print(result.json())


def benchmark_media(net, args):
    # Generate the config for the client quacker, if enabled
    if args.client_quacker:
        quacker = QuackerConfig.from_args(args)
    else:
        quacker = None

    # Create the benchmark and run it
    bm = MediaBenchmark(
        net,
        label=args.label,
        logdir=args.logdir,
        duration=args.duration,
        frequency=args.frequency,
        ack_delay=args.ack_delay,
        quacker=quacker,
        proxy_type=args.proxy,
    )
    result = bm.run_benchmark(
        args.trials,
        args.timeout,
        args.network_statistics,
    )
    print(result.json())


def benchmark_iperf3(net, args):
    bm = Iperf3Benchmark(
        net,
        args.n,
        cca=args.congestion_control,
        proxy_type=args.proxy,
    )
    bm.run(
        args.label,
        args.logdir,
        args.trials,
        args.timeout,
        args.network_statistics,
        args.additional_data
    )


def parse_data_size(n):
    try:
        multiplier = 1
        if 'K' in n:
            multiplier = 1000
        elif 'M' in n:
            multiplier = 1000000
        elif 'G' in n:
            multiplier = 1000000000
        else:
            return int(n)
        return multiplier * int(n[:-1])
    except Exception:
        raise ValueError(f'invalid data size {n}')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='Sidekick',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(required=True)
    cli = subparsers.add_parser('cli')
    cli.set_defaults(ty='cli')

    ###########################################################################
    # Experiment configurations
    ###########################################################################
    exp_config = parser.add_argument_group('exp_config')
    exp_config.add_argument('-t', '--trials', type=int, default=1,
        help='Number of trials')
    exp_config.add_argument('--timeout', type=int,
        help='Experiment timeout, in seconds')
    exp_config.add_argument('--label', type=str, default='NO_LABEL')
    exp_config.add_argument('--logdir', type=str, default='/tmp/sidekick-logs',
        help='Directory where host logs are written, in server.log and client.log')
    exp_config.add_argument('--network-statistics', action='store_true',
        help='Include measured network statistics in experiment output')
    exp_config.add_argument('--tcpdump', action='store_true',
        help='Collect packet traces at each interface of each host in --logdir')
    exp_config.add_argument('--perf', action='store_true',
        help='Collect perf reports at the proxy and server')
    exp_config.add_argument('--debug', action='store_true',
        help='More verbose debug logging')
    exp_config.add_argument('--topology',
        choices=['one_hop', 'direct'], default='one_hop',
        help='Network topology to use. If "direct", uses the network path '\
             'properties for the "near path segment" i.e. Link 1.')

    ###########################################################################
    # Network Configurations
    ###########################################################################
    net_config = parser.add_argument_group('net_config')
    net_config.add_argument('--delay1', type=int, default=1, metavar='MS',
        help='1/2 RTT on near path segment')
    net_config.add_argument('--delay2', type=int, default=25, metavar='MS',
        help='1/2 RTT on far path segment')
    net_config.add_argument('--loss1', type=str, default='1', metavar='PERCENT',
        help='loss (in %%) on near path segment')
    net_config.add_argument('--loss2', type=str, default='0', metavar='PERCENT',
        help='loss (in %%) on near path segment')
    net_config.add_argument('--bw1', type=int, default=100, metavar='MBPS',
        help='link bandwidth (in Mbps) on near path segment')
    net_config.add_argument('--bw2', type=int, default=10, metavar='MBPS',
        help='link bandwidth (in Mbps) on far path segment')
    net_config.add_argument('--jitter1', type=int, metavar='MS',
        help='jitter on near path segment with a default delay correlation '\
            f'of {DEFAULT_DELAY_CORR}%% and a paretonormal distribution')
    net_config.add_argument('--jitter2', type=int, metavar='MS',
        help='jitter on far path segment with a default delay correlation '\
            f'of {DEFAULT_DELAY_CORR}%% and a paretonormal distribution')
    net_config.add_argument('--qdisc', type=str, default='red',
        choices=['red', 'bfifo-large', 'bfifo-small', 'pie', 'codel',
                 'policer', 'fq_codel'],
        help='netem queuing discipline')

    ###########################################################################
    # Proxy configurations
    ###########################################################################
    proxy_config = parser.add_argument_group('proxy_config')
    proxy_config.add_argument('--proxy', type=ProxyType, choices=list(ProxyType))
    proxy_config.add_argument('--quacker', action='store_true',
        help='Enable a sniffer on the client to send quacks to the proxy')
    proxy_config.add_argument('--threshold', type=int, default=20,
        help='If --quacker is enabled, the threshold number of missing '\
             'packets that the quack can detect')
    proxy_config.add_argument('--freq-ms', metavar='MS', type=int, default=50,
        help='The quacker quacks on the first insertion, AND if --freq-pkts '\
             'have been inserted or at least --freq-ms have elapsed since '\
             'the last quack.')
    proxy_config.add_argument('--freq-pkts', metavar='PKTS', type=int, default=0,
        help='The quacker quacks on the first insertion, AND if --freq-pkts '\
             'have been inserted or at least --freq-ms have elapsed since '\
             'the last quack.')
    proxy_config.add_argument('--quackee-port', type=int, default=5252,
        help='If a quacker is enabled, the UDP port that the quackee on the '\
             'proxy is listening on for quacks')

    ###########################################################################
    # HTTP/1.1+TCP benchmark
    ###########################################################################
    tcp = subparsers.add_parser(
        'tcp',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    tcp.set_defaults(ty='benchmark', benchmark=benchmark_tcp)
    tcp.add_argument('-n', type=parse_data_size, default=1000000,
        help='Number of bytes to download in the HTTP/1.1 GET request, '\
             'e.g., 1000, 1K, 1M, 1000000, 1G')
    tcp.add_argument('-cca', '--congestion-control',
        choices=['reno', 'cubic', 'bbr', 'bbr2'], default='cubic',
        help='Congestion control algorithm at endpoints')
    tcp.add_argument('--certfile', type=str, default=DEFAULT_SSL_CERTFILE,
        help='Path to SSL certificate')
    tcp.add_argument('--keyfile', type=str, default=DEFAULT_SSL_KEYFILE_TCP,
        help='Path to SSL key')

    ###########################################################################
    # HTTP/3+QUIC benchmark
    ###########################################################################
    quic = subparsers.add_parser(
        'quic',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    quic.set_defaults(ty='benchmark', benchmark=benchmark_google_quic)
    quic.add_argument('-n', type=parse_data_size, default=1000000,
        help='Number of bytes to download in the HTTP/3 GET request, '\
             'e.g., 1000, 1K, 1M, 1000000, 1G')
    quic.add_argument('-cca', '--congestion-control',
        choices=['cubic', 'reno', 'bbr1', 'bbr'], default='cubic',
        help='Congestion control algorithm at endpoints')
    quic.add_argument('--certfile', type=str, default=DEFAULT_SSL_CERTFILE,
        help='Path to SSL certificate')
    quic.add_argument('--keyfile', type=str, default=DEFAULT_SSL_KEYFILE_QUIC,
        help='Path to SSL key')

    ###########################################################################
    # HTTP/3+Cloudflare QUIC benchmark
    ###########################################################################
    quiche = subparsers.add_parser(
        'quiche',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    quiche.set_defaults(ty='benchmark', benchmark=benchmark_cloudflare_quic)
    quiche.add_argument('-n', type=parse_data_size, default=1000000,
        help='Number of bytes to download in the HTTP/3 GET request, '\
             'e.g., 1000, 1K, 1M, 1000000, 1G')
    quiche.add_argument('-cca', '--congestion-control',
        choices=['cubic', 'reno', 'bbr2', 'bbr'], default='cubic',
        help='Congestion control algorithm at endpoints')
    quiche.add_argument('--certfile', type=str, default=DEFAULT_SSL_CERTFILE,
        help='Path to SSL certificate')
    quiche.add_argument('--keyfile', type=str, default=DEFAULT_SSL_KEYFILE_TCP,
        help='Path to SSL key')

    ###########################################################################
    # HTTP/3+picoquic QUIC benchmark
    ###########################################################################
    picoquic = subparsers.add_parser(
        'picoquic',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    picoquic.set_defaults(ty='benchmark', benchmark=benchmark_picoquic)
    picoquic.add_argument('-n', type=parse_data_size, default=1000000,
        help='Number of bytes to download in the HTTP/3 GET request, '\
             'e.g., 1000, 1K, 1M, 1000000, 1G')
    picoquic.add_argument('--client-quacker', action='store_true',
        help='Enable an in-line quacker with the client to quack to the proxy')
    picoquic.add_argument('--ack-delay', type=int, default=0, metavar='MS',
        help='Delay (ms) of sidekick ACK signal to reduce spurious retx')
    picoquic.add_argument('-cca', '--congestion-control',
        choices=['newreno', 'cubic', 'dcubic', 'fast', 'bbr', 'prague', 'bbr1'], default='cubic',
        help='Congestion control algorithm at endpoints')
    picoquic.add_argument('--certfile', type=str, default=DEFAULT_SSL_CERTFILE,
        help='Path to SSL certificate')
    picoquic.add_argument('--keyfile', type=str, default=DEFAULT_SSL_KEYFILE_TCP,
        help='Path to SSL key')

    ###########################################################################
    # Media Benchmark
    ###########################################################################
    media = subparsers.add_parser(
        'media',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    media.set_defaults(ty='benchmark', benchmark=benchmark_media)
    media.add_argument('--duration', type=int, default=1, metavar='SECS',
        help='Number of seconds to stream data before sending a timeout.')
    media.add_argument('--frequency', type=int, default=20, metavar='MS',
        help='Frequency at which to send data packets. The payload size is '\
             '240 bytes.')
    media.add_argument('--client-quacker', action='store_true',
        help='Enable an in-line quacker with the client to quack to the proxy')
    media.add_argument('--ack-delay', type=int, default=0, metavar='MS',
        help='Delay (ms) of NACK signal to reduce spurious retransmissions')

    ###########################################################################
    # Iperf3 + TCP Benchmark
    ###########################################################################
    iperf3 = subparsers.add_parser(
        'iperf3',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    iperf3.set_defaults(ty='benchmark', benchmark=benchmark_iperf3)
    iperf3.add_argument('--additional_data', action='store_true',
                        help='Include full iperf3 json output in results')
    iperf3.add_argument('-n', type=parse_data_size, default=1000000,
        help='Number of bytes to transfer via iperf3, '\
             'e.g., 1000, 1K, 1M, 1000000, 1G')
    iperf3.add_argument('-cca', '--congestion-control',
        choices=['cubic', 'bbr'], default='cubic',
        help='Congestion control algorithm at endpoints')

    return parser.parse_args(args=argv)


def main(args):
    # Some BBR implementations require pacing.
    # This includes Cloudflare quiche and Linux kernel versions <5.0.
    # We automatically set pacing for Linux TCP BBR, but we need to set it
    # here for user-space implementations.
    if args.ty != 'cli' and args.benchmark == benchmark_cloudflare_quic and 'bbr' in args.congestion_control:
        pacing = True
    else:
        pacing = False

    if args.topology == 'one_hop':
        net = OneHopNetwork(args.delay1, args.delay2, args.loss1, args.loss2,
            args.bw1, args.bw2, args.jitter1, args.jitter2, args.qdisc, pacing,
            perf=args.perf, debug=args.debug,
            bridge_proxy=args.proxy is None,
            router_proxy=args.proxy == ProxyType.PEPSAL)
    elif args.topology == 'direct':
        assert args.proxy is None
        net = DirectNetwork(args.delay1, args.loss1, args.bw1, args.jitter1,
            args.qdisc, pacing, perf=args.perf, debug=args.debug)
    else:
        raise NotImplementedError(args.topology)

    try:
        init_logdir(args.logdir)

        # Start the network proxy if configured
        proxy_logfile = f'{args.logdir}/{ROUTER_LOGFILE}'
        if args.proxy == ProxyType.PEPSAL:
            net.start_tcp_pep(proxy_logfile)
        elif args.proxy == ProxyType.BRIDGE:
            net.start_bridge(proxy_logfile)
        elif args.proxy == ProxyType.SIDEKICK:
            net.start_sidekick(args.threshold, args.quackee_port,
                logfile=proxy_logfile)

        # Start the packet trace collector
        if args.tcpdump:
            net.start_tcpdump(args.logdir)

        # Start the client quacker if using a sniffing version
        if args.quacker:
            client_logfile = f'{args.logdir}/{CLIENT_LOGFILE}'
            config = QuackerConfig.from_args(args)
            net.start_client_quacker(config, logfile=client_logfile)

        if args.ty == 'cli':
            CLI(net.net)
        else:
            time.sleep(1)
            args.benchmark(net, args)
    finally:
        net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    args = parse_args()
    main(args)
