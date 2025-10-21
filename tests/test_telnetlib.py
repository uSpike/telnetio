import contextlib
import re
import selectors
import socket
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing
from typing import Any, Protocol

import pytest

from telnetio import telnetlib

tl = telnetlib


class HasFileno(Protocol):
    def fileno(self) -> int: ...


def server(evt: threading.Event, sock: socket.socket) -> None:
    try:
        conn, addr = sock.accept()
        evt.wait()
        conn.close()
    except TimeoutError:
        pass


class TestGeneral:
    @pytest.fixture(autouse=True)
    def sock_tuple(self) -> Iterator[tuple[str, int]]:
        evt = threading.Event()

        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("", 0))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(5)
            sock.listen()

            thread = threading.Thread(target=server, args=(evt, sock))
            thread.daemon = True
            thread.start()
            try:
                yield sock.getsockname()
            finally:
                evt.set()
                thread.join()

    def testBasic(self, sock_tuple: tuple[str, int]) -> None:
        # connects
        telnet = telnetlib.Telnet(*sock_tuple)
        telnet.close()

    def testContextManager(self, sock_tuple: tuple[str, int]) -> None:
        with telnetlib.Telnet(*sock_tuple) as tn:
            assert tn.get_socket() is not None

        with pytest.raises(RuntimeError):
            # XXX: This is different than the stdlib!
            # stdlib returns None, but typeshed only specifies socket return
            # Therefore, this library will raise
            tn.get_socket()

    def testTimeoutDefault(self, sock_tuple: tuple[str, int]) -> None:
        assert socket.getdefaulttimeout() is None
        socket.setdefaulttimeout(30)
        try:
            telnet = telnetlib.Telnet(*sock_tuple)
        finally:
            socket.setdefaulttimeout(None)
        assert telnet.sock is not None
        assert telnet.sock.gettimeout() == 30
        telnet.close()

    def testTimeoutNone(self, sock_tuple: tuple[str, int]) -> None:
        # None, having other default
        assert socket.getdefaulttimeout() is None
        socket.setdefaulttimeout(30)
        try:
            telnet = telnetlib.Telnet(*sock_tuple, timeout=None)
        finally:
            socket.setdefaulttimeout(None)
        assert telnet.sock is not None
        assert telnet.sock.gettimeout() is None
        telnet.close()

    def testTimeoutValue(self, sock_tuple: tuple[str, int]) -> None:
        telnet = telnetlib.Telnet(*sock_tuple, timeout=30)
        assert telnet.sock is not None
        assert telnet.sock.gettimeout() == 30
        telnet.close()

    def testTimeoutOpen(self, sock_tuple: tuple[str, int]) -> None:
        telnet = telnetlib.Telnet()
        telnet.open(*sock_tuple, timeout=30)
        assert telnet.sock is not None
        assert telnet.sock.gettimeout() == 30
        telnet.close()

    def testGetters(self, sock_tuple: tuple[str, int]) -> None:
        # Test telnet getter methods
        telnet = telnetlib.Telnet(*sock_tuple, timeout=30)
        t_sock = telnet.sock
        assert t_sock is not None
        assert telnet.get_socket() == t_sock
        assert telnet.fileno() == t_sock.fileno()
        telnet.close()


class SocketStub:
    """a socket proxy that re-defines sendall()"""

    def __init__(self, reads: Sequence[bytes] = ()):
        self.reads = list(reads)  # Intentionally make a copy.
        self.writes: list[bytes] = []
        self.block = False

    def sendall(self, data: bytes) -> None:
        self.writes.append(data)

    def recv(self, size: int) -> bytes:
        out = b""
        while self.reads and len(out) < size:
            out += self.reads.pop(0)
        if len(out) > size:
            self.reads.insert(0, out[size:])
            out = out[:size]
        return out


class TelnetAlike(telnetlib.Telnet):
    def fileno(self) -> int:
        raise NotImplementedError()

    def close(self) -> None:
        pass

    def sock_avail(self) -> bool:
        assert self.sock is not None
        return not self.sock.block  # type: ignore[attr-defined]


class MockSelector(selectors.BaseSelector):
    def __init__(self) -> None:
        self.keys: dict[int | HasFileno, selectors.SelectorKey] = {}

    @property
    def resolution(self) -> float:
        return 1e-3

    def register(self, fileobj: int | HasFileno, events: int, data: Any = None) -> selectors.SelectorKey:
        key = selectors.SelectorKey(fileobj, 0, events, data)
        self.keys[fileobj] = key
        return key

    def unregister(self, fileobj: int | HasFileno) -> selectors.SelectorKey:
        return self.keys.pop(fileobj)

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        block = False
        for fileobj in self.keys:
            if isinstance(fileobj, TelnetAlike):
                assert fileobj.sock is not None
                block = fileobj.sock.block  # type: ignore[attr-defined]
                break
        if block:
            return []
        else:
            return [(key, key.events) for key in self.keys.values()]

    def get_map(self) -> dict[int | HasFileno, selectors.SelectorKey]:
        return self.keys


@contextlib.contextmanager
def _test_socket(reads: Sequence[bytes]) -> Iterator[None]:
    def new_conn(*ignored: Any) -> SocketStub:
        return SocketStub(reads)

    try:
        old_conn = socket.create_connection
        socket.create_connection = new_conn  # type: ignore[assignment]
        yield None
    finally:
        socket.create_connection = old_conn
    return


def _test_telnet(reads: Sequence[bytes] = ()) -> telnetlib.Telnet:
    """return a telnetlib.Telnet object that uses a SocketStub with
    reads queued up to be read"""
    with _test_socket(reads):
        telnet = TelnetAlike("dummy", 0)
    return telnet


class TestExpectAndReadTestCase:
    @pytest.fixture(autouse=True)
    def selector(self) -> Iterator[None]:
        self.old_selector = telnetlib._TelnetSelector
        telnetlib._TelnetSelector = MockSelector
        yield
        telnetlib._TelnetSelector = self.old_selector


class TestRead(TestExpectAndReadTestCase):
    def test_read_until(self) -> None:
        """
        read_until(expected, timeout=None)
        test the blocking version of read_util
        """
        want = [b"xxxmatchyyy"]
        telnet = _test_telnet(want)
        data = telnet.read_until(b"match")
        assert data == b"xxxmatch"

        reads = [b"x" * 50, b"match", b"y" * 50]
        expect = b"".join(reads[:-1])
        telnet = _test_telnet(reads)
        data = telnet.read_until(b"match")
        assert data == expect

    def test_read_all(self) -> None:
        """
        read_all()
          Read all data until EOF; may block.
        """
        reads = [b"x" * 500, b"y" * 500, b"z" * 500]
        expect = b"".join(reads)
        telnet = _test_telnet(reads)
        data = telnet.read_all()
        assert data == expect
        return

    def test_read_some(self) -> None:
        """
        read_some()
          Read at least one byte or EOF; may block.
        """
        # test 'at least one byte'
        telnet = _test_telnet([b"x" * 500])
        data = telnet.read_some()
        assert len(data) >= 1
        # test EOF
        telnet = _test_telnet()
        data = telnet.read_some()
        assert b"" == data

    def _read_eager(self, func_name: str) -> None:
        """
        read_*_eager()
          Read all data available already queued or on the socket,
          without blocking.
        """
        want = b"x" * 100
        telnet = _test_telnet([want])
        func = getattr(telnet, func_name)
        assert telnet.sock is not None
        telnet.sock.block = True  # type: ignore[attr-defined]
        assert b"" == func()
        telnet.sock.block = False  # type: ignore[attr-defined]
        data = b""
        while True:
            try:
                data += func()
            except EOFError:
                break
        assert data == want

    def test_read_eager(self) -> None:
        # read_eager and read_very_eager make the same guarantees
        # (they behave differently but we only test the guarantees)
        self._read_eager("read_eager")
        self._read_eager("read_very_eager")
        # NB -- we need to test the IAC block which is mentioned in the
        # docstring but not in the module docs

    def read_very_lazy(self) -> None:
        want = b"x" * 100
        telnet = _test_telnet([want])
        assert b"" == telnet.read_very_lazy()
        assert telnet.sock is not None
        while telnet.sock.reads:  # type: ignore[attr-defined]
            telnet.fill_rawq()
        data = telnet.read_very_lazy()
        assert want == data
        with pytest.raises(EOFError):
            telnet.read_very_lazy()

    def test_read_lazy(self) -> None:
        want = b"x" * 100
        telnet = _test_telnet([want])
        assert b"" == telnet.read_lazy()
        data = b""
        while True:
            try:
                read_data = telnet.read_lazy()
                data += read_data
                if not read_data:
                    telnet.fill_rawq()
            except EOFError:
                break
            assert want.startswith(data)
        assert data == want


class nego_collector:
    def __init__(self, sb_getter: Callable[..., bytes] | None = None) -> None:
        self.seen = b""
        self.sb_getter = sb_getter
        self.sb_seen = b""

    def do_nego(self, sock: socket.socket, cmd: bytes, opt: bytes) -> None:
        self.seen += cmd + opt
        if cmd == tl.SE and self.sb_getter:
            sb_data = self.sb_getter()
            self.sb_seen += sb_data


class TestWrite:
    """The only thing that write does is replace each tl.IAC for
    tl.IAC+tl.IAC"""

    def test_write(self) -> None:
        data_sample = [
            b"data sample without IAC",
            b"data sample with" + tl.IAC + b" one IAC",
            b"a few" + tl.IAC + tl.IAC + b" iacs" + tl.IAC,
            tl.IAC,
            b"",
        ]
        for data in data_sample:
            telnet = _test_telnet()
            assert telnet.sock is not None
            telnet.write(data)
            written = b"".join(telnet.sock.writes)  # type: ignore[attr-defined]
            assert data.replace(tl.IAC, tl.IAC + tl.IAC) == written


class TestOption:
    # RFC 854 commands
    cmds = [tl.AO, tl.AYT, tl.BRK, tl.EC, tl.EL, tl.GA, tl.IP, tl.NOP]

    def _test_command(self, data: Sequence[bytes]) -> None:
        """helper for testing IAC + cmd"""
        telnet = _test_telnet(data)
        data_len = len(b"".join(data))
        nego = nego_collector()
        telnet.set_option_negotiation_callback(nego.do_nego)
        txt = telnet.read_all()
        cmd = nego.seen
        assert len(cmd) > 0  # we expect at least one command
        assert cmd[:1] in self.cmds
        assert cmd[1:2] == tl.NOOPT
        assert data_len == len(txt + cmd)

    @pytest.mark.parametrize("cmd", cmds)
    def test_IAC_command(self, cmd: bytes) -> None:
        self._test_command([tl.IAC, cmd])
        self._test_command([b"x" * 100, tl.IAC, cmd, b"y" * 100])
        self._test_command([b"x" * 10, tl.IAC, cmd, b"y" * 10])

    def test_IAC_commands(self) -> None:
        # all at once
        self._test_command([tl.IAC + cmd for (cmd) in self.cmds])

    def test_SB_commands(self) -> None:
        # RFC 855, subnegotiations portion
        send = [
            tl.IAC + tl.SB + tl.IAC + tl.SE,
            tl.IAC + tl.SB + tl.IAC + tl.IAC + tl.IAC + tl.SE,
            tl.IAC + tl.SB + tl.IAC + tl.IAC + b"aa" + tl.IAC + tl.SE,
            tl.IAC + tl.SB + b"bb" + tl.IAC + tl.IAC + tl.IAC + tl.SE,
            tl.IAC + tl.SB + b"cc" + tl.IAC + tl.IAC + b"dd" + tl.IAC + tl.SE,
        ]
        telnet = _test_telnet(send)
        telnet.debuglevel = 1
        nego = nego_collector(telnet.read_sb_data)
        telnet.set_option_negotiation_callback(nego.do_nego)
        txt = telnet.read_all()
        assert txt == b""
        want_sb_data = tl.IAC + tl.IAC + b"aabb" + tl.IAC + b"cc" + tl.IAC + b"dd"
        assert nego.sb_seen == want_sb_data
        assert b"" == telnet.read_sb_data()

    def test_debuglevel_reads(self, capsys: Any) -> None:
        # test all the various places that self.msg(...) is called
        given_a_expect_b = [
            # Telnet.fill_rawq
            (b"a", ": recv b''\n"),
            # Telnet.process_rawq
            (tl.IAC + bytes([88]), ": IAC 88 not recognized\n"),
            (tl.IAC + tl.DO + bytes([1]), ": IAC DO 1\n"),
            (tl.IAC + tl.DONT + bytes([1]), ": IAC DONT 1\n"),
            (tl.IAC + tl.WILL + bytes([1]), ": IAC WILL 1\n"),
            (tl.IAC + tl.WONT + bytes([1]), ": IAC WONT 1\n"),
        ]
        for a, b in given_a_expect_b:
            telnet = _test_telnet([a])
            telnet.set_debuglevel(1)
            telnet.read_all()
            assert b in capsys.readouterr().out
        return

    def test_debuglevel_write(self, capsys: Any) -> None:
        telnet = _test_telnet()
        telnet.set_debuglevel(1)
        telnet.write(b"xxx")
        expected = "send b'xxx'\n"
        assert expected in capsys.readouterr().out

    def test_debug_accepts_str_port(self, capsys: Any) -> None:
        # Issue 10695
        with _test_socket([]):
            telnet = TelnetAlike("dummy", "1")
        telnet.set_debuglevel(1)
        telnet.msg("test")
        assert re.search(r"1.*test", capsys.readouterr().out)


class TestExpect(TestExpectAndReadTestCase):
    def test_expect(self) -> None:
        """
        expect(expected, [timeout])
          Read until the expected string has been seen, or a timeout is
          hit (default is no timeout); may block.
        """
        want = [b"x" * 10, b"match", b"y" * 10]
        telnet = _test_telnet(want)
        (_, _, data) = telnet.expect([b"match"])
        assert data == b"".join(want[:-1])
