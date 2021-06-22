from dataclasses import dataclass
from typing import Callable, Generator, List, Optional

from ._opt import Opt

StateCoroutine = Generator[None, int, None]


class Event:
    def as_bytes(self) -> bytes:
        raise NotImplementedError()


@dataclass(frozen=True)
class Data(Event):
    contents: bytearray

    def as_bytes(self) -> bytes:
        return bytes(self.contents)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Data":
        return cls(bytearray(data))


@dataclass(frozen=True)
class Command(Event):
    cmd: Opt
    opt: Optional[int]

    def as_bytes(self) -> bytes:
        data = bytes([self.cmd])
        if self.opt is not None:
            data += bytes([self.opt])
        return data


@dataclass(frozen=True)
class SubCommand(Event):
    cmd: Opt
    opts: bytearray

    def as_bytes(self) -> bytes:
        return bytes([self.cmd]) + self.opts


@dataclass(frozen=True)
class UnknownCommand(Event):
    cmd: int


class TelnetMachine:
    """
    Sans-IO telnet state machine
    """

    #: List of IAC commands needing multiple (3) bytes
    _iac_mbs = (Opt.DO, Opt.DONT, Opt.WILL, Opt.WONT)

    def __init__(self) -> None:
        self._state: StateCoroutine = self._state_data()
        next(self._state)  # prime
        self._next_state: Callable[[], StateCoroutine] = self._state_data
        self._events: List[Event] = []
        self._data = bytearray()

    def receive_data(self, data: bytes) -> List[Event]:
        """
        Receive data from a stream into the state machine.
        """
        for byte in data:
            try:
                self._state.send(byte)
            except StopIteration:
                self._state = self._next_state()
                next(self._state)  # prime

        events = self._events.copy()
        if self._data:
            events.append(Data(self._data.copy()))
            self._data.clear()
        self._events.clear()
        return events

    def send(self, data: bytes) -> bytes:
        """
        Parses data to be sent to the stream.
        """
        data = data.replace(bytes([Opt.IAC]), bytes([Opt.IAC, Opt.IAC]))
        return bytes(data)

    def send_event(self, event: Event) -> bytes:
        """
        Send an event object to the stream.
        """
        return event.as_bytes()

    def _state_data(self) -> StateCoroutine:
        while True:
            char = yield
            if char == Opt.IAC:
                self._next_state = self._state_iac
                return
            elif char != Opt.NULL:
                self._data.append(char)

    def _state_iac(self) -> StateCoroutine:
        cmd = yield
        self._next_state = self._state_data
        if cmd in self._iac_mbs:
            # These commands are 3-byte
            opt = yield
            self._events.append(Command(Opt(cmd), opt))
        elif cmd == Opt.IAC:
            # escaped IAC
            self._data.append(Opt.IAC)
        elif cmd == Opt.SB:
            self._next_state = self._state_sb
        else:
            self._events.append(UnknownCommand(cmd))

    def _state_sb(self) -> StateCoroutine:
        buf = bytearray()
        self._next_state = self._state_data

        while True:
            data = yield
            if data == Opt.IAC:
                opt = yield
                if opt == Opt.SE:
                    if not buf:
                        ValueError("SE: buffer empty")
                    if buf[0] == Opt.NULL:
                        raise ValueError("SE: buffer is NUL")
                    if len(buf) == 1:
                        raise ValueError("SE: buffer too short")

                    cmd = Opt(buf[0])
                    event = SubCommand(cmd, buf[1:])
                    self._events.append(event)
                    break
                elif opt == Opt.IAC:
                    # escaped IAC
                    buf.append(Opt.IAC)
            else:
                buf.append(data)
