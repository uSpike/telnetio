"""TELNET client class.

This is a best-effort implementation of ``telnetlib`` from the Python standard
library taken from 3.11, though the code has not changed significantly since
python 2.x.
The intention is for users of ``telnetlib`` to simply install this library and
only need to change their imports from:

    import telnetlib

to:

    from telnetio import telnetlib


Compatibility is only guaranteed for documented methods and attributes.

Example:

    >>> from telnetio.telnetlib import Telnet
    >>> tn = Telnet("www.python.org", 79)  # connect to finger port
    >>> tn.write(b"guido\r\n")
    >>> print(tn.read_all())
    Login       Name               TTY         Idle    When    Where
    guido    Guido van Rossum      pts/2        <Dec  2 11:10> snag.cnri.reston..

Note that read_all() won't read until eof -- it just reads some data
-- but it guarantees to read at least one byte unless EOF is hit.

It is possible to pass a Telnet object to a selector in order to wait until
more data is available.  Note that in this case, read_eager() may return b''
even if there was data on the socket, because the protocol negotiation may have
eaten the data.  This is why EOFError is needed in some cases to distinguish
between "no data" and "connection closed" (since the socket also appears ready
for reading when it is closed).
"""

from __future__ import annotations

import re
import selectors
import socket
import sys
from re import Match, Pattern
from time import monotonic
from typing import TYPE_CHECKING, Any, TypeVar

from . import opt
from ._machine import Command, Data, Error, ErrorKind, SubCommand, TelnetMachine

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import TracebackType

__all__ = ["Telnet"]

T = TypeVar("T", bound="Telnet")

# This is how the stdlib library did it...
_DEFAULT_TIMEOUT = socket._GLOBAL_DEFAULT_TIMEOUT  # type: ignore[attr-defined]

# Tunable parameters
DEBUGLEVEL = 0

# Telnet protocol defaults
TELNET_PORT = 23

# Telnet protocol characters (don't change)
IAC = bytes([opt.IAC])  # "Interpret As Command"
DONT = bytes([opt.DONT])
DO = bytes([opt.DO])
WONT = bytes([opt.WONT])
WILL = bytes([opt.WILL])
theNULL = bytes([opt.NULL])

SE = bytes([opt.SE])  # Subnegotiation End
NOP = bytes([opt.NOP])  # No Operation
DM = bytes([opt.DM])  # Data Mark
BRK = bytes([opt.BRK])  # Break
IP = bytes([opt.IP])  # Interrupt process
AO = bytes([opt.AO])  # Abort output
AYT = bytes([opt.AYT])  # Are You There
EC = bytes([opt.EC])  # Erase Character
EL = bytes([opt.EL])  # Erase Line
GA = bytes([opt.GA])  # Go Ahead
SB = bytes([opt.SB])  # Subnegotiation Begin


# Telnet protocol options code (don't change)
# These ones all come from arpa/telnet.h
BINARY = bytes([opt.BINARY])  # 8-bit data path
ECHO = bytes([opt.ECHO])  # echo
RCP = bytes([opt.RCP])  # prepare to reconnect
SGA = bytes([opt.SGA])  # suppress go ahead
NAMS = bytes([opt.NAMS])  # approximate message size
STATUS = bytes([opt.STATUS])  # give status
TM = bytes([opt.TM])  # timing mark
RCTE = bytes([opt.RCTE])  # remote controlled transmission and echo
NAOL = bytes([opt.NAOL])  # negotiate about output line width
NAOP = bytes([opt.NAOP])  # negotiate about output page size
NAOCRD = bytes([opt.NAOCRD])  # negotiate about CR disposition
NAOHTS = bytes([opt.NAOHTS])  # negotiate about horizontal tabstops
NAOHTD = bytes([opt.NAOHTD])  # negotiate about horizontal tab disposition
NAOFFD = bytes([opt.NAOFFD])  # negotiate about formfeed disposition
NAOVTS = bytes([opt.NAOVTS])  # negotiate about vertical tab stops
NAOVTD = bytes([opt.NAOVTD])  # negotiate about vertical tab disposition
NAOLFD = bytes([opt.NAOLFD])  # negotiate about output LF disposition
XASCII = bytes([opt.XASCII])  # extended ascii character set
LOGOUT = bytes([opt.LOGOUT])  # force logout
BM = bytes([opt.BM])  # byte macro
DET = bytes([opt.DET])  # data entry terminal
SUPDUP = bytes([opt.SUPDUP])  # supdup protocol
SUPDUPOUTPUT = bytes([opt.SUPDUPOUTPUT])  # supdup output
SNDLOC = bytes([opt.SNDLOC])  # send location
TTYPE = bytes([opt.TTYPE])  # terminal type
EOR = bytes([opt.EOR])  # end or record
TUID = bytes([opt.TUID])  # TACACS user identification
OUTMRK = bytes([opt.OUTMRK])  # output marking
TTYLOC = bytes([opt.TTYLOC])  # terminal location number
VT3270REGIME = bytes([opt.VT3270REGIME])  # 3270 regime
X3PAD = bytes([opt.X3PAD])  # X.3 PAD
NAWS = bytes([opt.NAWS])  # window size
TSPEED = bytes([opt.TSPEED])  # terminal speed
LFLOW = bytes([opt.LFLOW])  # remote flow control
LINEMODE = bytes([opt.LINEMODE])  # Linemode option
XDISPLOC = bytes([opt.XDISPLOC])  # X Display Location
OLD_ENVIRON = bytes([opt.OLD_ENVIRON])  # Old - Environment variables
AUTHENTICATION = bytes([opt.AUTHENTICATION])  # Authenticate
ENCRYPT = bytes([opt.ENCRYPT])  # Encryption option
NEW_ENVIRON = bytes([opt.NEW_ENVIRON])  # New - Environment variables
# the following ones come from
# http://www.iana.org/assignments/telnet-options
# Unfortunately, that document does not assign identifiers
# to all of them, so we are making them up
TN3270E = bytes([opt.TN3270E])  # TN3270E
XAUTH = bytes([opt.XAUTH])  # XAUTH
CHARSET = bytes([opt.CHARSET])  # CHARSET
RSP = bytes([opt.RSP])  # Telnet Remote Serial Port
COM_PORT_OPTION = bytes([opt.COM_PORT_OPTION])  # Com Port Control Option
SUPPRESS_LOCAL_ECHO = bytes([opt.SUPPRESS_LOCAL_ECHO])  # Telnet Suppress Local Echo
TLS = bytes([opt.TLS])  # Telnet Start TLS
KERMIT = bytes([opt.KERMIT])  # KERMIT
SEND_URL = bytes([opt.SEND_URL])  # SEND-URL
FORWARD_X = bytes([opt.FORWARD_X])  # FORWARD_X
PRAGMA_LOGON = bytes([opt.PRAGMA_LOGON])  # TELOPT PRAGMA LOGON
SSPI_LOGON = bytes([opt.SSPI_LOGON])  # TELOPT SSPI LOGON
PRAGMA_HEARTBEAT = bytes([opt.PRAGMA_HEARTBEAT])  # TELOPT PRAGMA HEARTBEAT
EXOPL = bytes([opt.IAC])  # Extended-Options-List
NOOPT = bytes([opt.NULL])


# poll/select have the advantage of not requiring any extra file descriptor,
# contrarily to epoll/kqueue (also, they require a single syscall).
_TelnetSelector: type[selectors.BaseSelector]

if hasattr(selectors, "PollSelector"):
    _TelnetSelector = selectors.PollSelector
else:  # pragma: nocover
    _TelnetSelector = selectors.SelectSelector


class Telnet:
    """Telnet interface class.

    An instance of this class represents a connection to a telnet
    server.  The instance is initially not connected; the open()
    method must be used to establish a connection.  Alternatively, the
    host name and optional port number can be passed to the
    constructor, too.

    Don't try to reopen an already connected instance.

    This class has many read_*() methods.  Note that some of them
    raise EOFError when the end of the connection is read, because
    they can return an empty string for other reasons.  See the
    individual doc strings.

    read_until(expected, [timeout])
        Read until the expected string has been seen, or a timeout is
        hit (default is no timeout); may block.

    read_all()
        Read all data until EOF; may block.

    read_some()
        Read at least one byte or EOF; may block.

    read_very_eager()
        Read all data available already queued or on the socket,
        without blocking.

    read_eager()
        Read either data already queued or some data available on the
        socket, without blocking.

    read_lazy()
        Read all data in the raw queue (processing it first), without
        doing any socket I/O.

    read_very_lazy()
        Reads all data in the cooked queue, without doing any socket
        I/O.

    read_sb_data()
        Reads available data between SB ... SE sequence. Don't block.

    set_option_negotiation_callback(callback)
        Each time a telnet option is read on the input flow, this callback
        (if set) is called with the following parameters :
        callback(telnet socket, command, option)
            option will be chr(0) when there is no option.
        No other action is done afterwards by telnetlib.
    """

    def __init__(self, host: str | None = None, port: int | str = 0, timeout: float | None = _DEFAULT_TIMEOUT) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._machine = TelnetMachine()
        self.sock: socket.socket | None = None
        self.eof = 0
        self.debuglevel = DEBUGLEVEL
        self.option_callback: Callable[[socket.socket, bytes, bytes], object] | None = None
        self.cookedq = b""
        self.sbdataq = b""

        if self.host is not None:
            self.open(self.host, self.port, self.timeout)

    def open(self, host: str, port: int = 0, timeout: float | None = _DEFAULT_TIMEOUT) -> None:
        """Connect to a host.

        The optional second argument is the port number, which
        defaults to the standard telnet port (23).

        Don't try to reopen an already connected instance.
        """
        self.eof = 0
        if port == 0:
            port = TELNET_PORT
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), timeout)

    def __del__(self) -> None:
        """Destructor -- close the connection."""
        self.close()

    def msg(self, msg: str, *args: Any) -> None:
        """Print a debug message, when the debug level is > 0.

        If extra arguments are present, they are substituted in the
        message using the standard string formatting operator.
        """
        if self.debuglevel > 0:
            print(f"Telnet({self.host},{self.port}): {msg % args}")

    def set_debuglevel(self, debuglevel: int) -> None:
        """Set the debug level.

        The higher it is, the more debug output you get (on sys.stdout).
        """
        self.debuglevel = debuglevel

    def close(self) -> None:
        """Close the connection."""
        if self.sock is not None:
            self.sock.close()

        self.sock = None
        self.eof = 1

    def get_socket(self) -> socket.socket:
        """Return the socket object.

        This method in the stdlib can return ``None`` but typeshed specifies only ``socket``
        as the return type.  Therefore we will raise `RuntimeError` if the telnet object
        has been closed.
        """
        if self.sock is None:  # pragma: nocover
            raise RuntimeError()

        return self.sock

    def fileno(self) -> int:
        """Return the fileno() of the socket object used internally."""
        if self.sock is None:  # pragma: nocover
            raise RuntimeError()

        return self.sock.fileno()

    def write(self, buffer: bytes) -> None:
        """Write a string to the socket, doubling any IAC characters.

        Can block if the connection is blocked.  May raise
        OSError if the connection is closed.
        """
        if self.sock is None:  # pragma: nocover
            raise RuntimeError()

        buffer = self._machine.send_message(buffer)
        self.msg(f"send {buffer!r}")
        self.sock.sendall(buffer)

    def read_until(self, match: bytes, timeout: float | None = None) -> bytes:
        """Read until a given string is encountered or until timeout.

        When no match is found, return whatever is available instead,
        possibly the empty string.  Raise EOFError if the connection
        is closed and no cooked data is available.
        """

        def _do_match(start: int | None) -> bytes | None:
            i = self.cookedq.find(match, start)
            if i >= 0:
                i += len(match)
                buf = self.cookedq[:i]
                self.cookedq = self.cookedq[i:]
                return buf
            else:
                return None

        buf = _do_match(start=None)
        if buf is not None:
            return buf

        deadline = 0.0

        if timeout is not None:
            deadline = monotonic() + timeout

        with _TelnetSelector() as selector:
            selector.register(self, selectors.EVENT_READ)
            while not self.eof:
                if selector.select(timeout):
                    i = max(0, len(self.cookedq) - len(match))
                    self._receive()
                    buf = _do_match(start=i)
                    if buf is not None:
                        return buf
                if timeout is not None:
                    timeout = deadline - monotonic()
                    if timeout < 0:
                        break

        return self.read_very_lazy()

    def read_all(self) -> bytes:
        """Read all data until EOF; block until connection closed."""
        while not self.eof:
            self._receive()

        buf = self.cookedq
        self.cookedq = b""
        return buf

    def read_some(self) -> bytes:
        """Read at least one byte of cooked data unless EOF is hit.

        Return b'' if EOF is hit.  Block if no data is immediately
        available.
        """
        while not self.cookedq and not self.eof:
            self._receive()

        buf = self.cookedq
        self.cookedq = b""
        return buf

    def read_very_eager(self) -> bytes:
        """Read everything that's possible without blocking in I/O (eager).

        Raise EOFError if connection closed and no cooked data
        available.  Return b'' if no cooked data available otherwise.
        Don't block unless in the midst of an IAC sequence.
        """
        while not self.eof and self.sock_avail():
            self._receive()
        return self.read_very_lazy()

    def read_eager(self) -> bytes:
        """Read readily available data.

        Raise EOFError if connection closed and no cooked data
        available.  Return b'' if no cooked data available otherwise.
        Don't block unless in the midst of an IAC sequence.
        """
        while not self.cookedq and not self.eof and self.sock_avail():
            self._receive()

        return self.read_very_lazy()

    def read_lazy(self) -> bytes:
        """Process and return data that's already in the queues (lazy).

        Raise EOFError if connection closed and no data available.
        Return b'' if no cooked data available otherwise.  Don't block
        unless in the midst of an IAC sequence.
        """
        return self.read_very_lazy()

    def read_very_lazy(self) -> bytes:
        """Return any data available in the cooked queue (very lazy).

        Raise EOFError if connection closed and no data available.
        Return b'' if no cooked data available otherwise.  Don't block.
        """
        buf = self.cookedq
        self.cookedq = b""
        if not buf and self.eof:
            raise EOFError("telnet connection closed")
        return buf

    def read_sb_data(self) -> bytes:
        """Return any data available in the SB ... SE queue.

        Return b'' if no SB ... SE available. Should only be called
        after seeing a SB or SE command. When a new SB command is
        found, old unread SB data will be discarded. Don't block.
        """
        buf = self.sbdataq
        self.sbdataq = b""
        return buf

    def set_option_negotiation_callback(self, callback: Callable[[socket.socket, bytes, bytes], object] | None) -> None:
        """Provide a callback function called after each receipt of a telnet option."""
        self.option_callback = callback

    def fill_rawq(self) -> None:
        """Included for historical use"""
        self._receive()

    def sock_avail(self) -> bool:
        """Test whether data is available on the socket."""
        with _TelnetSelector() as selector:
            selector.register(self, selectors.EVENT_READ)
            return bool(selector.select(0))

    def interact(self) -> None:
        """Interaction function, emulates a very dumb telnet client."""
        if sys.platform == "win32":
            self.mt_interact()
            return
        with _TelnetSelector() as selector:
            selector.register(self, selectors.EVENT_READ)
            selector.register(sys.stdin, selectors.EVENT_READ)

            while True:
                for key, events in selector.select():
                    if key.fileobj is self:
                        try:
                            text = self.read_eager()
                        except EOFError:
                            print("*** Connection closed by remote host ***")
                            return
                        if text:
                            sys.stdout.write(text.decode("ascii"))
                            sys.stdout.flush()
                    elif key.fileobj is sys.stdin:
                        line = sys.stdin.readline().encode("ascii")
                        if not line:
                            return
                        self.write(line)

    def mt_interact(self) -> None:
        """Multithreaded version of interact()."""
        import _thread

        _thread.start_new_thread(self.listener, ())
        while 1:
            line = sys.stdin.readline()
            if not line:
                break
            self.write(line.encode("ascii"))

    def listener(self) -> None:
        """Helper for mt_interact() -- this executes in the other thread."""
        while 1:
            try:
                data = self.read_eager()
            except EOFError:
                print("*** Connection closed by remote host ***")
                return
            if data:
                sys.stdout.write(data.decode("ascii"))
            else:
                sys.stdout.flush()

    def expect(
        self, list: Sequence[Pattern[bytes] | bytes], timeout: float | None = None
    ) -> tuple[int, Match[bytes] | None, bytes]:
        """Read until one from a list of a regular expressions matches.

        The first argument is a list of regular expressions, either
        compiled (re.Pattern instances) or uncompiled (strings).
        The optional second argument is a timeout, in seconds; default
        is no timeout.

        Return a tuple of three items: the index in the list of the
        first regular expression that matches; the re.Match object
        returned; and the text read up till and including the match.

        If EOF is read and no text was read, raise EOFError.
        Otherwise, when nothing matches, return (-1, None, text) where
        text is the text received so far (may be the empty string if a
        timeout happened).

        If a regular expression ends with a greedy match (e.g. '.*')
        or if more than one expression can match the same input, the
        results are undeterministic, and may depend on the I/O timing.
        """
        if timeout is not None:
            deadline = monotonic() + timeout

        with _TelnetSelector() as selector:
            selector.register(self, selectors.EVENT_READ)
            while not self.eof:
                for i in range(len(list)):
                    m = re.search(list[i], self.cookedq)
                    if m is not None:
                        e = m.end()
                        text = self.cookedq[:e]
                        self.cookedq = self.cookedq[e:]
                        return (i, m, text)
                if timeout is not None:
                    ready = selector.select(timeout)
                    timeout = deadline - monotonic()
                    if not ready:
                        if timeout < 0:
                            break
                        else:
                            continue

                self._receive()

        text = self.read_very_lazy()
        if not text and self.eof:
            raise EOFError

        return (-1, None, text)

    def __enter__(self: T) -> T:
        return self

    def __exit__(
        self, type: type[BaseException] | None, value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()

    # These methods are added to support the telnetio backend

    def _handle_data(self, event: Data) -> None:
        self.cookedq += event.msg

    def _handle_command(self, event: Command) -> None:
        if self.sock is None:  # pragma: nocover
            raise RuntimeError()

        if event.opt is not None:  # 3-byte command
            name = {opt.DO: "DO", opt.DONT: "DONT", opt.WILL: "WILL", opt.WONT: "WONT"}.get(event.cmd, "?")
            self.msg(f"IAC {name} {event.opt}")

            if self.option_callback is not None:
                self.option_callback(self.sock, bytes([event.cmd]), bytes([event.opt]))
            elif event.cmd in (opt.DO, opt.DONT):
                self.sock.sendall(bytes([opt.IAC, opt.WONT, event.opt]))
            elif event.cmd in (opt.WILL, opt.WONT):
                self.sock.sendall(bytes([opt.IAC, opt.DONT, event.opt]))
        else:
            if self.option_callback is not None:
                self.option_callback(self.sock, bytes([event.cmd]), NOOPT)
            else:
                self.msg(f"IAC {event.cmd} not recognized")

    def _handle_subcommand(self, event: SubCommand) -> None:
        # Callback is supposed to look into the sbdataq
        self._do_subcommand_callback(bytes([event.cmd]) + event.opts)

    def _handle_error(self, event: Error) -> None:
        if event.kind is ErrorKind.SE_BUFFER_TOO_SHORT:
            # allow option callback to handle data even if its too short
            # this is how the original library worked
            self._do_subcommand_callback(event.data)
        else:
            self.msg(str(event))

    def _do_subcommand_callback(self, data: bytes) -> None:
        if self.sock is None:  # pragma: nocover
            raise RuntimeError()

        self.sbdataq += data
        if self.option_callback is not None:
            self.option_callback(self.sock, bytes([opt.SB]), NOOPT)
            self.option_callback(self.sock, bytes([opt.SE]), NOOPT)

    def _receive(self) -> None:
        if self.sock is None:  # pragma: nocover
            raise RuntimeError()

        buf = self.sock.recv(50)
        self.msg(f"recv {buf!r}")
        self.eof = int(not buf)

        for event in self._machine.receive_data(buf):
            if isinstance(event, Data):
                self._handle_data(event)
            elif isinstance(event, Command):
                self._handle_command(event)
            elif isinstance(event, SubCommand):
                self._handle_subcommand(event)
            elif isinstance(event, Error):
                self._handle_error(event)


def test() -> None:
    """Test program for telnetlib.

    Usage: python -m telnetio.telnetlib [-d] ... [host [port]]

    Default host is localhost; default port is 23.
    """
    debuglevel = 0
    while sys.argv[1:] and sys.argv[1] == "-d":
        debuglevel = debuglevel + 1
        del sys.argv[1]

    host = "localhost"
    if sys.argv[1:]:
        host = sys.argv[1]

    port = 0
    if sys.argv[2:]:
        portstr = sys.argv[2]
        try:
            port = int(portstr)
        except ValueError:
            port = socket.getservbyname(portstr, "tcp")

    with Telnet() as tn:
        tn.set_debuglevel(debuglevel)
        tn.open(host, port, timeout=0.5)
        tn.interact()


if __name__ == "__main__":
    test()
