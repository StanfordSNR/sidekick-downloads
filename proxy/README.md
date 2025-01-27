# Proxy Library and Binaries

This currently contains one example: a transparent bridge

To build:

```
proxy$ cargo build --bin bridge
```

To run (from a proxy):

```
$ ./{proxy-dir}/target/debug/bridge -i {iface1} -o {iface2}
```

Where `iface1` and `iface2` are names of interfaces, e.g. "eth0".

This can optionally be prefixed with a [log level](https://docs.rs/log/latest/log/enum.Level.html), e.g.:

```
$ RUST_LOG=trace ./{proxy-dir}/target/debug/bridge -i {iface1} -o {iface2}
```