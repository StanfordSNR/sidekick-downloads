# Proxy Library and Binaries

To build the Sidekick proxy:

```
proxy$ cargo build --bin sidekick --release
```

Or, in debug mode:

```
proxy$ cargo build --bin sidekick
```

To run (from a proxy):

```
$ ./{proxy-dir}/target/debug/sidekick -i {iface1} -o {iface2}
```

Where `iface1` and `iface2` are names of interfaces, e.g. "eth0".

This can optionally be prefixed with a [log level](https://docs.rs/log/latest/log/enum.Level.html), e.g.:

```
$ RUST_LOG=trace ./{proxy-dir}/target/debug/sidekick -i {iface1} -o {iface2}
```

The proxy/examples directory also contains a transparent bridge program, which can be used for testing.