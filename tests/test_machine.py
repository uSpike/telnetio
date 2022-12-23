from telnetio import Command, Data, Error, ErrorKind, SubCommand, TelnetMachine, opt


def test_machine_receive() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"0123") == [Data(b"0"), Data(b"1"), Data(b"2"), Data(b"3")]


def test_machine_receive_escaped_iac() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"01\xff\xff23") == [Data(b"0"), Data(b"1"), Data(b"\xff"), Data(b"2"), Data(b"3")]


def test_machine_receive_negotation_3_byte() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"foo" + bytes([opt.IAC, opt.WILL, opt.ECHO]) + b"bar") == [
        Data(b"f"),
        Data(b"o"),
        Data(b"o"),
        Command(opt.WILL, opt.ECHO),
        Data(b"b"),
        Data(b"a"),
        Data(b"r"),
    ]


def test_machine_receive_command() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.IP])) == [Command(opt.IP)]


def test_machine_receive_subnegotiation() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.SB, opt.WILL, opt.ECHO, opt.IAC, opt.SE])) == [
        SubCommand(opt.WILL, bytearray([opt.ECHO]))
    ]


def test_machine_receive_newline_cr() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"\r\0") == [Data(b"\r")]


def test_machine_receive_newline_lf() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"\r\n") == [Data(b"\n")]


def test_machine_receive_newline_iac() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"\r" + bytes([opt.IAC, opt.WILL, opt.ECHO])) == [
        Data(b"\r"),
        Command(opt.WILL, opt.ECHO),
    ]


def test_machine_receive_newline_data() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(b"\r" + b"0123") == [Data(b"\r0"), Data(b"1"), Data(b"2"), Data(b"3")]


def test_machine_sb_empty() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.SB, opt.IAC, opt.SE])) == [Error(ErrorKind.SE_BUFFER_EMPTY)]


def test_machine_sb_null() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.SB, 0, opt.IAC, opt.SE])) == [Error(ErrorKind.SE_BUFFER_NUL)]
    assert tn.receive_data(b"1234") == [Data(b"1"), Data(b"2"), Data(b"3"), Data(b"4")]


def test_machine_sb_too_short() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.SB, 1, opt.IAC, opt.SE])) == [
        Error(ErrorKind.SE_BUFFER_TOO_SHORT, data=bytes([1]))
    ]
    assert tn.receive_data(b"1234") == [Data(b"1"), Data(b"2"), Data(b"3"), Data(b"4")]


def test_machine_sb_escaped_iac() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.SB, opt.WILL, opt.IAC, opt.IAC, opt.IAC, opt.SE])) == [
        SubCommand(opt.WILL, bytearray([opt.IAC]))
    ]


def test_machine_sb_invalid() -> None:
    tn = TelnetMachine()
    assert tn.receive_data(bytes([opt.IAC, opt.SB, opt.WILL, opt.IAC, 0])) == [
        Error(ErrorKind.SB_INVALID, data=bytes([0]))
    ]


def test_machine_send() -> None:
    tn = TelnetMachine()
    assert tn.send_message(b"01234") == b"01234"
    assert tn.send_message(b"56") == b"56"


def test_machine_send_command() -> None:
    tn = TelnetMachine()
    assert tn.send_command(opt.WILL, opt.ECHO) == bytes([opt.IAC, opt.WILL, opt.ECHO])


def test_data_to_bytes() -> None:
    assert Data(b"0").as_bytes() == b"0"


def test_command_to_bytes() -> None:
    assert Command(opt.SB).as_bytes() == bytes([opt.IAC, opt.SB])
    assert Command(opt.WILL, opt.ECHO).as_bytes() == bytes([opt.IAC, opt.WILL, opt.ECHO])


def test_subcommand_to_bytes() -> None:
    assert SubCommand(opt.WILL, bytearray([opt.ECHO])).as_bytes() == bytearray([opt.WILL, opt.ECHO])
