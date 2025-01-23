import os
import select
import sys
import subprocess
import re

SERVER_LOGFILE = 'server.log'
CLIENT_LOGFILE = 'client.log'
ROUTER_LOGFILE = 'router.log'

SETUP_TIMEOUT = 10
LINUX_TIMEOUT_EXITCODE = 124
HTTP_OK_STATUSCODE = 200
HTTP_TIMEOUT_STATUSCODE = 408

# Log a benchmark result every this number of seconds so there is console
# output, even if there are still trials remaining.
LOG_CHUNK_TIME = 300

DEFAULT_DELAY_CORR = 40

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
    for filename in [SERVER_LOGFILE, CLIENT_LOGFILE, ROUTER_LOGFILE]:
        filename = f'{path}/{filename}'
        with open(filename, 'w') as _:
            pass

def read_subprocess_pipe(p):
    while p.poll() is None:
        ready, _, _ = select.select([p.stdout, p.stderr], [], [])
        for stream in ready:
            for line in stream.readlines():
                yield (line, stream)
    stdout, stderr = p.communicate()
    for line in stdout.splitlines(keepends=True):
        yield (line, p.stdout)
    for line in stderr.splitlines(keepends=True):
        yield (line, p.stderr)

def handle_background_process(p, logfile, func):
    with open(logfile, 'a') if logfile else None as f:
        for line, stream in read_subprocess_pipe(p):
            if f is not None:
                f.write(line)
            if func is not None:
                func(line)

def get_linux_version():
    proc = subprocess.run(['uname', '-r'], capture_output=True, text=True, check=True)
    version = proc.stdout.strip()
    return float(re.search(r'^\d+\.\d+', version).group())