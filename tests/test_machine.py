from typing import List, Union

from telnetio import Command, Event, Opt, SubCommand, TelnetMachine


class Telnet:
    def __init__(self) -> None:
        self.tn = TelnetMachine()
        self.received: List[Union[Event, bytes]] = []
        self.send = bytearray()
        self.tn.register_event_cb(self.received.append)
        self.tn.register_receive_cb(self.received.append)
        self.tn.register_send_cb(self.send.extend)

    def clear(self) -> None:
        self.received.clear()
        self.send.clear()

    def receive_data(self, data: bytes) -> None:
        self.tn.receive_data(data)

    def send_message(self, data: bytes) -> None:
        self.tn.send_message(data)


def test_machine_receive() -> None:
    tn = Telnet()
    tn.receive_data(b"01234")
    assert tn.received == [b"01234"]
    tn.clear()

    tn.receive_data(b"0123\xff")
    assert tn.received == [b"0123"]

    tn.receive_data(b"\xff")
    assert tn.received == [b"0123", b"\xff"]
    tn.clear()

    tn.receive_data(b"foo" + bytes([Opt.IAC, Opt.WILL, Opt.ECHO]) + b"bar")
    assert tn.received == [b"foo", Command(Opt.WILL, Opt.ECHO), b"bar"]
    tn.clear()

    tn.receive_data(bytes([Opt.IAC, Opt.SB, Opt.WILL, Opt.ECHO, Opt.IAC, Opt.SE]))
    assert tn.received == [SubCommand(Opt.WILL, bytearray([Opt.ECHO]))]


def test_machine_send() -> None:
    tn = Telnet()
    tn.send_message(b"01234")
    assert tn.send == b"01234"
    tn.send_message(b"56")
    assert tn.send == b"0123456"
