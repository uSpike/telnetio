from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional

from telnetio import opt

NUL = 0
LF = 10
CR = 13


@dataclass
class TelnetOption:
    """
    Tracks the status of telnet options
    """

    local_option: Optional[bool] = None
    remote_option: Optional[bool] = None
    reply_pending: bool = False


class State(Enum):
    #: Receiving normal data
    DATA = auto()
    #: Receiving data after CR received
    DATA_CR = auto()
    #: IAC
    COMMAND = auto()
    #: IAC with multiple (3) bytes
    NEGOTIATION = auto()
    #: Subnegotation option
    SUBN_OPTION = auto()
    #: Subnegotation sub-opion
    SUBN_SUBOPTION = auto()
    #: Subnegotation data
    SUBN_DATA = auto()
    #: Subnegotation end
    SUBN_END = auto()


class ErrorKind(Enum):
    SE_BUFFER_EMPTY = auto()
    SE_BUFFER_NUL = auto()
    SE_BUFFER_TOO_SHORT = auto()
    SB_INVALID = auto()
    OTHER = auto()


class Event(ABC):
    @abstractmethod
    def as_bytes(self) -> bytes:  # pragma: nocover
        ...


@dataclass(frozen=True)
class Error(Event):
    kind: ErrorKind
    data: bytes = b""

    def as_bytes(self) -> bytes:  # pragma: nocover
        raise NotImplementedError()


@dataclass(frozen=True)
class Data(Event):
    msg: bytes

    def as_bytes(self) -> bytes:
        return self.msg


@dataclass(frozen=True)
class Command(Event):
    cmd: int
    opt: Optional[int] = None  # only included for 3-byte commands

    def as_bytes(self) -> bytes:
        data = bytes([opt.IAC, self.cmd])
        if self.opt is not None:
            data += bytes([self.opt])
        return data


@dataclass(frozen=True)
class SubCommand(Event):
    cmd: int
    opts: bytearray

    def as_bytes(self) -> bytes:
        return bytes([self.cmd]) + self.opts


class TelnetMachine:
    """
    Sans-IO telnet state machine.
    """

    #: List of IAC commands needing multiple (3) bytes
    _iac_mbs = (opt.DO, opt.DONT, opt.WILL, opt.WONT)

    def __init__(self) -> None:
        self._state = State.DATA
        self._buffer = bytearray()

    def receive_data(self, data: bytes) -> List[Event]:
        out: List[Event] = []
        for char in data:
            event = self._receive_byte(char)
            if event is not None:
                out.append(event)
        return out

    def _receive_byte(self, char: int) -> Optional[Event]:
        """
        Receive data from a stream into the state machine.
        """
        # `int.to_bytes()` (57ns) is faster than `bytes([int])` (114ns)
        char_byte = char.to_bytes(1, "little")  # endianness doesn't matter

        if self._state == State.DATA:
            if char == opt.IAC:
                self._state = State.COMMAND
                return None
            elif char == CR:
                self._state = State.DATA_CR
                return None
            else:
                return Data(char_byte)

        elif self._state == State.DATA_CR:
            # previous char was CR
            self._state = State.DATA

            if char == LF:
                return Data(b"\n")
            elif char == NUL:
                return Data(b"\r")
            elif char == opt.IAC:
                # IAC isn't allowed after \r according to the
                # RFC, but handling this way is less surprising than
                # delivering the IAC as normal data.
                self._state = State.COMMAND
                return Data(b"\r")
            else:
                return Data(b"\r" + char_byte)

        elif self._state == State.COMMAND:
            # received IAC
            self._state = State.DATA

            if char in self._iac_mbs:
                self._buffer.append(char)
                self._state = State.NEGOTIATION
                return None
            elif char == opt.SB:
                self._state = State.SUBN_OPTION
                return None
            elif char == opt.IAC:
                # escaped IAC
                return Data(char_byte)
            else:
                return Command(char)

        elif self._state == State.NEGOTIATION:
            self._state = State.DATA
            cmd = self._buffer.pop()
            self._buffer.clear()
            return Command(cmd, char)

        elif self._state == State.SUBN_OPTION:
            # opt.SB was sent
            if char == opt.IAC:
                self._state = State.SUBN_END
                return None

            self._buffer.append(char)
            self._state = State.SUBN_SUBOPTION
            return None

        elif self._state == State.SUBN_SUBOPTION:
            if char == opt.IAC:
                self._state = State.SUBN_END
                return None

            self._buffer.append(char)
            self._state = State.SUBN_DATA
            return None

        elif self._state == State.SUBN_DATA:
            if char == opt.IAC:
                self._state = State.SUBN_END
                return None
            else:
                self._buffer.append(char)
                return None

        elif self._state == State.SUBN_END:
            if char == opt.IAC:
                # Repeated IAC is treated as data
                self._state = State.SUBN_DATA
                self._buffer.append(char)
                return None
            elif char == opt.SE:
                self._state = State.DATA
                buf = self._buffer.copy()
                self._buffer.clear()

                if not buf:
                    return Error(ErrorKind.SE_BUFFER_EMPTY)
                if buf[0] == opt.NULL:
                    return Error(ErrorKind.SE_BUFFER_NUL)
                if len(buf) == 1:
                    return Error(ErrorKind.SE_BUFFER_TOO_SHORT, data=bytes(buf))

                cmd = buf[0]
                return SubCommand(cmd, buf[1:])
            else:
                self._buffer.clear()
                self._state = State.DATA
                return Error(ErrorKind.SB_INVALID, data=bytes([char]))
        else:
            raise RuntimeError(f"Unreachable state {self._state}")  # pragma: nocover

    def send_message(self, data: bytes) -> bytes:
        """
        Send a message (text) to the stream.
        """
        return data.replace(bytes([opt.IAC]), bytes([opt.IAC, opt.IAC]))

    def send_command(self, cmd: int, opt: Optional[int] = None) -> bytes:
        return Command(cmd, opt).as_bytes()


class TelnetClient:
    def __init__(self, machine: TelnetMachine) -> None:
        self._machine = machine
        self._options: Dict[int, TelnetOption] = defaultdict(TelnetOption)

    def on_event(self, event: Event) -> None:
        if isinstance(event, Command):
            if event.opt is None:
                raise ValueError()
            if event.cmd == opt.DO:
                return self.handle_do(event.opt)
            elif event.cmd == opt.DONT:
                return self.handle_dont(event.opt)
            elif event.cmd == opt.WILL:
                return self.handle_will(event.opt)
            elif event.cmd == opt.WONT:
                return self.handle_wont(event.opt)

    def check_local_option(self, option: int) -> bool:
        return self._options[option].local_option or False

    def check_remote_option(self, option: int) -> bool:
        return self._options[option].remote_option or False

    def handle_do(self, option: int) -> None:
        self._options[option].reply_pending = False

        if option == opt.ECHO:
            # DE requests us to echo their input
            if not self._options[opt.ECHO].local_option:
                self._options[opt.ECHO].local_option = True
                self._machine.send_command(opt.WILL, opt.ECHO)

        elif option == opt.BINARY:
            # DE requests us to receive BINARY
            if not self._options[opt.BINARY].local_option:
                self._options[opt.BINARY].local_option = True
                self._machine.send_command(opt.WILL, opt.BINARY)

        elif option == opt.SGA:
            # DE wants us to suppress go-ahead
            if not self._options[opt.SGA].local_option:
                self._options[opt.SGA].local_option = True
                self._machine.send_command(opt.WILL, opt.SGA)
                self._machine.send_command(opt.DO, opt.SGA)

    def handle_dont(self, option: int) -> None:
        pass

    def handle_will(self, option: int) -> None:
        pass

    def handle_wont(self, option: int) -> None:
        pass


class TelnetServer:
    def __init__(self, machine: TelnetMachine) -> None:
        self._machine = machine
        self._options: Dict[int, TelnetOption] = defaultdict(TelnetOption)
