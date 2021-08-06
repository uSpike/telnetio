from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, Iterable, Iterator, List, Optional, Union

from ._opt import Opt

StateCoroutine = Generator[None, int, None]
BacklogItem = Union["Event", bytes]
EventCallback = Callable[["Event"], Any]
DataCallback = Callable[[bytes], Any]

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


class Event(ABC):
    @abstractmethod
    def as_bytes(self) -> bytes:  # pragma: nocover
        ...


@dataclass(frozen=True)
class Command(Event):
    cmd: Opt
    opt: Optional[int] = None  # only included for 3-byte commands

    def as_bytes(self) -> bytes:
        data = bytes([Opt.IAC, self.cmd])
        if self.opt is not None:
            data += bytes([self.opt])
        return data


@dataclass(frozen=True)
class SubCommand(Event):
    cmd: Opt
    opts: bytearray

    def as_bytes(self) -> bytes:
        return bytes([self.cmd]) + self.opts


class Backlog(Iterable[BacklogItem]):
    def __init__(self) -> None:
        self.data: List[BacklogItem] = []

    def __iter__(self) -> Iterator[BacklogItem]:
        return iter(self.data)

    def clear(self) -> None:
        self.data.clear()

    def add_message(self, data: bytes) -> None:
        if not self.data or not isinstance(self.data[-1], bytes):
            self.data.append(data)
        else:
            self.data[-1] += data

    def add_event(self, event: Event) -> None:
        self.data.append(event)


class TelnetMachine:
    """
    Sans-IO telnet state machine.
    """

    #: List of IAC commands needing multiple (3) bytes
    _iac_mbs = (Opt.DO, Opt.DONT, Opt.WILL, Opt.WONT)

    def __init__(self) -> None:
        self._state: StateCoroutine = self._state_data()
        next(self._state)  # prime
        self._next_state: Callable[[], StateCoroutine] = self._state_data
        self._backlog = Backlog()
        self._leftover = bytearray()
        self._event_callbacks: List[EventCallback] = []
        self._receive_callbacks: List[DataCallback] = []
        self._send_callbacks: List[DataCallback] = []

    def register_event_cb(self, callback: EventCallback) -> None:
        """
        Register a callback for every event created.
        """
        self._event_callbacks.append(callback)

    def register_receive_cb(self, callback: DataCallback) -> None:
        """
        Register a callback for message data that was received.
        """
        self._receive_callbacks.append(callback)

    def register_send_cb(self, callback: DataCallback) -> None:
        """
        Register a callback for raw data that needs to be sent.
        """
        self._send_callbacks.append(callback)

    def receive_data(self, data: bytes) -> None:
        """
        Receive data from a stream into the state machine.
        """
        data = self._leftover + data
        self._leftover.clear()
        for idx, byte in enumerate(data):
            try:
                self._state.send(byte)
            except StopIteration:
                self._state = self._next_state()
                next(self._state)  # prime
            except:
                self._leftover.extend(data[idx:])
                raise

        for event_or_data in self._backlog:
            if isinstance(event_or_data, bytes):
                for recv_cb in self._receive_callbacks:
                    recv_cb(event_or_data)
            else:
                for event_cb in self._event_callbacks:
                    event_cb(event_or_data)
        self._backlog.clear()

    def send(self, data: bytes) -> None:
        """
        Send raw data to the stream.
        """
        for cb in self._send_callbacks:
            cb(data)

    def send_message(self, data: bytes) -> None:
        """
        Send a message (text) to the stream.
        """
        data = data.replace(bytes([Opt.IAC]), bytes([Opt.IAC, Opt.IAC]))
        self.send(data)

    def send_command(self, cmd: Opt, opt: Optional[int] = None) -> None:
        self.send(Command(cmd, opt).as_bytes())

    def _state_data(self) -> StateCoroutine:
        while True:
            char = yield

            if char == Opt.IAC:
                self._next_state = self._state_iac
                return
            elif char == CR:
                char_after_cr = yield

                if char_after_cr == LF:
                    self._backlog.add_message(b"\n")
                elif char_after_cr == NUL:
                    self._backlog.add_message(b"\r")
                elif char_after_cr == Opt.IAC:
                    # IAC isn't allowed after \r according to the
                    # RFC, but handling this way is less surprising than
                    # delivering the IAC as normal data.
                    self._backlog.add_message(b"\r")
                    self._next_state = self._state_iac
                    return
                else:
                    self._backlog.add_message(b"\r" + bytes([char_after_cr]))
            else:
                self._backlog.add_message(bytes([char]))

    def _state_iac(self) -> StateCoroutine:
        self._next_state = self._state_data

        cmd = yield
        if cmd in self._iac_mbs:
            # These commands are 3-byte
            opt = yield
            self._backlog.add_event(Command(Opt(cmd), opt))
        elif cmd == Opt.IAC:
            # escaped IAC
            self._backlog.add_message(bytes([Opt.IAC]))
        elif cmd == Opt.SB:
            self._next_state = self._state_sb
        else:
            self._backlog.add_event(Command(Opt(cmd)))

    def _state_sb(self) -> StateCoroutine:
        buf = bytearray()
        self._next_state = self._state_data

        while True:
            data = yield
            if data == Opt.IAC:
                opt = yield
                if opt == Opt.SE:
                    if not buf:
                        raise ValueError("SE: buffer empty")
                    if buf[0] == Opt.NULL:
                        raise ValueError("SE: buffer is NUL")
                    if len(buf) == 1:
                        raise ValueError("SE: buffer too short")

                    cmd = Opt(buf[0])
                    self._backlog.add_event(SubCommand(cmd, buf[1:]))
                    break
                elif opt == Opt.IAC:
                    # escaped IAC
                    buf.append(Opt.IAC)
            else:
                buf.append(data)


class TelnetClient:
    def __init__(self, machine: TelnetMachine) -> None:
        self._machine = machine
        self._machine.register_event_cb(self.on_event)
        self._options: Dict[int, TelnetOption] = defaultdict(TelnetOption)

    def on_event(self, event: Event) -> None:
        if isinstance(event, Command):
            if event.opt is None:
                raise ValueError()
            if event.cmd == Opt.DO:
                return self.handle_do(event.opt)
            elif event.cmd == Opt.DONT:
                return self.handle_dont(event.opt)
            elif event.cmd == Opt.WILL:
                return self.handle_will(event.opt)
            elif event.cmd == Opt.WONT:
                return self.handle_wont(event.opt)

    def check_local_option(self, option: Opt) -> bool:
        return self._options[option].local_option or False

    def check_remote_option(self, option: Opt) -> bool:
        return self._options[option].remote_option or False

    def handle_do(self, option: int) -> None:
        self._options[option].reply_pending = False

        if option == Opt.ECHO:
            # DE requests us to echo their input
            if not self._options[Opt.ECHO].local_option:
                self._options[Opt.ECHO].local_option = True
                self._machine.send_command(Opt.WILL, Opt.ECHO)

        elif option == Opt.BINARY:
            # DE requests us to receive BINARY
            if not self._options[Opt.BINARY].local_option:
                self._options[Opt.BINARY].local_option = True
                self._machine.send_command(Opt.WILL, Opt.BINARY)

        elif option == Opt.SGA:
            # DE wants us to suppress go-ahead
            if not self._options[Opt.SGA].local_option:
                self._options[Opt.SGA].local_option = True
                self._machine.send_command(Opt.WILL, Opt.SGA)
                self._machine.send_command(Opt.DO, Opt.SGA)

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
