# emulation

For all options, see:

```
sudo -E python3 emulation/main.py --help
```

## Run TCP benchmark

```
sudo -E python3 emulation/main.py -t 5 tcp -n 100K [--proxy [proxy_type]]
```

## Start mininet CLI

```
sudo -E python3 emulation/main.py cli
```

## Run tests

Run all tests with `emulation/` as the working directory. `sudo` is required
because of mininet. Requires all dependencies to be installed.

```
sudo -E python3 -m unittest
```

Run tests that match a regex pattern:

```
sudo -E python3 -m unittest discover -k test_cli
```

Run tests that match a specific module:

```
sudo -E python3 -m unittest tests.test_network.TestPopen
```

## tcpdump

```
sudo -E python3 emulation/main.py --debug --tcpdump multicast --duration 1
tcpdump -r /tmp/sidekick-logs/p1-eth0.pcap | less
```