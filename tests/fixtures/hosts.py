"""Host values that tests use on purpose."""

# The IPv4 wildcard address, as a value under test: seagoat maps it to
# loopback and refuses to listen on it by default; no test binds to it
ALL_INTERFACES = "0.0.0.0"  # noqa: S104
