from typing import List

from telnetio import Command, Event, Opt, ReceiveMessage, SubCommand, TelnetMachine


def test_machine() -> None:
    tn = TelnetMachine()
    events: List[Event] = []
    tn.register_event_cb(events.append)

    tn.receive_data(b"01234")
    assert events == [ReceiveMessage(bytearray(b"01234"))]
    events.clear()

    tn.receive_data(b"0123\xff")
    assert events == [ReceiveMessage(bytearray(b"0123"))]
    events.clear()

    tn.receive_data(b"\xff")
    assert events == [ReceiveMessage(bytearray(b"\xff"))]
    events.clear()

    tn.receive_data(bytes([Opt.IAC, Opt.WILL, Opt.ECHO]))
    assert events == [Command(Opt.WILL, Opt.ECHO)]
    events.clear()

    tn.receive_data(bytes([Opt.IAC, Opt.SB, Opt.WILL, Opt.ECHO, Opt.IAC, Opt.SE]))
    assert events == [SubCommand(Opt.WILL, bytearray([Opt.ECHO]))]
