from typing import List, Union

import pytest

from telnetio import Command, Event, Opt, SubCommand, TelnetMachine


class Telnet:
    def __init__(self) -> None:
        self.machine = TelnetMachine()
        self.received: List[Union[Event, bytes]] = []
        self.send = bytearray()
        self.machine.register_event_cb(self.received.append)
        self.machine.register_receive_cb(self.received.append)
        self.machine.register_send_cb(self.send.extend)

    def clear(self) -> None:
        self.received.clear()
        self.send.clear()


def test_machine_receive() -> None:
    tn = Telnet()
    tn.machine.receive_data(b"01234")
    assert tn.received == [b"01234"]
    tn.clear()

    tn.machine.receive_data(b"0123\xff")
    assert tn.received == [b"0123"]

    tn.machine.receive_data(b"\xff")
    assert tn.received == [b"0123", b"\xff"]
    tn.clear()

    tn.machine.receive_data(b"foo" + bytes([Opt.IAC, Opt.WILL, Opt.ECHO]) + b"bar")
    assert tn.received == [b"foo", Command(Opt.WILL, Opt.ECHO), b"bar"]
    tn.clear()

    tn.machine.receive_data(bytes([Opt.IAC, Opt.IP]))
    assert tn.received == [Command(Opt.IP)]
    tn.clear()

    tn.machine.receive_data(bytes([Opt.IAC, Opt.SB, Opt.WILL, Opt.ECHO, Opt.IAC, Opt.SE]))
    assert tn.received == [SubCommand(Opt.WILL, bytearray([Opt.ECHO]))]


def test_machine_sb_empty() -> None:
    tn = Telnet()
    with pytest.raises(ValueError, match="SE: buffer empty"):
        tn.machine.receive_data(bytes([Opt.IAC, Opt.SB, Opt.IAC, Opt.SE]))


def test_machine_sb_null() -> None:
    tn = Telnet()
    with pytest.raises(ValueError, match="SE: buffer is NUL"):
        tn.machine.receive_data(bytes([Opt.IAC, Opt.SB, 0, Opt.IAC, Opt.SE]))

    tn.machine.receive_data(b"1234")
    assert tn.received == [b"1234"]


def test_machine_sb_too_short() -> None:
    tn = Telnet()
    with pytest.raises(ValueError, match="SE: buffer too short"):
        tn.machine.receive_data(bytes([Opt.IAC, Opt.SB, 1, Opt.IAC, Opt.SE]))

    tn.machine.receive_data(b"1234")
    assert tn.received == [b"1234"]


def test_machine_sb_escaped_iac() -> None:
    tn = Telnet()
    tn.machine.receive_data(bytes([Opt.IAC, Opt.SB, Opt.WILL, Opt.IAC, Opt.IAC, Opt.IAC, Opt.SE]))
    assert tn.received == [SubCommand(Opt.WILL, bytearray([Opt.IAC]))]


def test_machine_send() -> None:
    tn = Telnet()
    tn.machine.send_message(b"01234")
    assert tn.send == b"01234"
    tn.machine.send_message(b"56")
    assert tn.send == b"0123456"


def test_machine_send_command() -> None:
    tn = Telnet()
    tn.machine.send_command(Opt.WILL, Opt.ECHO)
    assert tn.send == bytes([Opt.IAC, Opt.WILL, Opt.ECHO])


def test_command_to_bytes() -> None:
    assert Command(Opt.SB).as_bytes() == bytes([Opt.IAC, Opt.SB])
    assert Command(Opt.WILL, Opt.ECHO).as_bytes() == bytes([Opt.IAC, Opt.WILL, Opt.ECHO])


def test_subcommand_to_bytes() -> None:
    assert SubCommand(Opt.WILL, bytearray([Opt.ECHO])).as_bytes() == bytearray([Opt.WILL, Opt.ECHO])
