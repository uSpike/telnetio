from ._machine import Command, Data, Error, ErrorKind, Event, SubCommand, TelnetClient, TelnetMachine, TelnetServer

__all__ = [
    "Command",
    "Data",
    "Error",
    "ErrorKind",
    "Event",
    "SubCommand",
    "TelnetClient",
    "TelnetMachine",
    "TelnetServer",
]

try:
    import anyio
except ImportError:  # pragma: nocover
    pass
else:
    from ._anyio import AnyioTelnetClient, AnyioTelnetServer

    __all__ += [
        "AnyioTelnetClient",
        "AnyioTelnetServer",
    ]
