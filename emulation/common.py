import os
import select
import sys
import subprocess
import re
from enum import Enum
from dataclasses import dataclass

SERVER_LOGFILE = 'server.log'
CLIENT_LOGFILE = 'client.log'
ROUTER_LOGFILE = 'router.log'

SETUP_TIMEOUT = 3
LINUX_TIMEOUT_EXITCODE = 124
HTTP_OK_STATUSCODE = 200
HTTP_TIMEOUT_STATUSCODE = 408

# Log a benchmark result every this number of seconds so there is console
# output, even if there are still trials remaining.
LOG_CHUNK_TIME = 300

DEFAULT_DELAY_CORR = 40

# If proxy needs to listen on a port, use this one.
PROXY_PORT = 10800

class ProxyType(Enum):
    PEPSAL = 'pepsal'
    BRIDGE = 'bridge'
    SIDEKICK = 'sidekick'
    SIDEKICK_MULTICAST = 'sidekick-multicast'
    PICOQUIC = 'picoquic'

@dataclass(frozen=True)
class QuackerConfig:
    # Whether to use the RIBLT quack
    riblt: bool
    # The threshold number of missing packets the quACK can find.
    threshold: int
    # The quacker quacks on the first insertion, AND if <freq_pkts> have been
    # inserted or at least <freq_ms> have elapsed since the last quack.
    freq_ms: int
    # The quacker quacks on the first insertion, AND if <freq_pkts> have been
    # inserted or at least <freq_ms> have elapsed since the last quack.
    freq_pkts: int
    # The UDP port that the quackee on the proxy is listening to for quACKs.
    quackee_port: int

    def from_args(args):
        return QuackerConfig(args.riblt, args.threshold, args.freq_ms,
                             args.freq_pkts, args.quackee_port)

def TRACE(val):
    # LOG(val, 'TRACE')
    pass

def DEBUG(val):
    LOG(val, 'DEBUG')

def INFO(val):
    LOG(val, 'INFO')

def WARN(val):
    LOG(val, 'WARN')

def ERROR(val):
    LOG(val, 'ERROR')

def LOG(val, level):
    print(f'[SIDEKICK:{level}] {val}', file=sys.stderr);

def init_logdir(path):
    os.system(f'mkdir -p {path}')
    os.system(f'rm {path}/*')

def read_subprocess_pipe(p):
    streams = [p.stdout, p.stderr]
    while p.poll() is None:
        ready, _, _ = select.select(streams, [], [])
        for stream in ready:
            while True:
                line = stream.readline()
                if not line:
                    break
                yield (line, stream)
    for stream in streams:
        for line in stream.readlines():
            yield (line, stream)
    stdout, stderr = p.communicate()
    for line in stdout.splitlines(keepends=True):
        yield (line, p.stdout)
    for line in stderr.splitlines(keepends=True):
        yield (line, p.stderr)

def handle_background_process(p, logfile, func):
    # Only call the callback function
    if logfile is None:
        for line, _ in read_subprocess_pipe(p):
            if func is not None:
                func(line)
        return

    # Both write to the logfile and call the callback function
    with open(logfile, 'a') as f:
        for line, _ in read_subprocess_pipe(p):
            if func is not None:
                func(line)
            f.write(line)

def get_linux_version():
    proc = subprocess.run(['uname', '-r'], capture_output=True, text=True, check=True)
    version = proc.stdout.strip()
    return float(re.search(r'^\d+\.\d+', version).group())
