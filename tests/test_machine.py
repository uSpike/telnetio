from telnetio import Command, Data, Opt, SubCommand, TelnetMachine


def test_machine() -> None:
    conn = TelnetMachine()
    assert conn.receive_data(b"01234") == [Data.from_bytes(b"01234")]
    assert conn.receive_data(b"0123\xff") == [Data.from_bytes(b"0123")]
    assert conn.receive_data(b"\xff") == [Data.from_bytes(b"\xff")]
    assert conn.receive_data(bytes([Opt.IAC, Opt.WILL, Opt.ECHO])) == [Command(Opt.WILL, Opt.ECHO)]
    assert conn.receive_data(bytes([Opt.IAC, Opt.SB, Opt.WILL, Opt.ECHO, Opt.IAC, Opt.SE])) == [
        SubCommand(Opt.WILL, bytearray([Opt.ECHO]))
    ]
