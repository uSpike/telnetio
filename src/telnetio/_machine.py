from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Generator, List, Optional

from ._opt import Opt

StateCoroutine = Generator[None, int, None]


@dataclass
class TelnetOption:
    """
    Tracks the status of telnet options
    """

    local_option: Optional[bool] = None
    remote_option: Optional[bool] = None
    reply_pending: bool = False


class Event:
    def as_bytes(self) -> bytes:
        raise NotImplementedError()


@dataclass(frozen=True)
class ReceiveMessage(Event):
    """
    Data (message) received
    """

    contents: bytearray

    def as_bytes(self) -> bytes:
        return bytes(self.contents)


@dataclass(frozen=True)
class SendData(Event):
    """
    Data (message) to be sent ASAP
    """

    contents: bytearray

    def as_bytes(self) -> bytes:
        return bytes(self.contents)


@dataclass(frozen=True)
class Command(Event):
    cmd: Opt
    opt: Opt = Opt.UNKNOWN  # default value indicates option is not included (2-byte command)

    def as_bytes(self) -> bytes:
        data = bytes([Opt.IAC, self.cmd])
        if self.opt is not Opt.UNKNOWN:
            data += bytes([self.opt])
        return data


@dataclass(frozen=True)
class SubCommand(Event):
    cmd: Opt
    opts: bytearray

    def as_bytes(self) -> bytes:
        return bytes([self.cmd]) + self.opts


class TelnetMachine:
    """
    Sans-IO telnet state machine.

    When an event occurs, `on_event` is called with that event as the sole argument.
    """

    #: List of IAC commands needing multiple (3) bytes
    _iac_mbs = (Opt.DO, Opt.DONT, Opt.WILL, Opt.WONT)

    def __init__(self) -> None:
        self._state: StateCoroutine = self._state_data()
        next(self._state)  # prime
        self._next_state: Callable[[], StateCoroutine] = self._state_data
        self._input_buffer = bytearray()
        self._event_backlog: List[Event] = []
        self._event_callbacks: List[Callable[[Event], None]] = []

        self.options: Dict[Opt, TelnetOption] = defaultdict(TelnetOption)

    def register_event_cb(self, callback: Callable[[Event], None]) -> None:
        """
        Register a callback for every event created.
        """
        self._event_callbacks.append(callback)

    def _create_event(self, event: Event) -> None:
        """
        Create an event and add it to the backlog to be fired later.
        """
        self._event_backlog.append(event)

    def _run_event_backlog(self) -> None:
        for event in self._event_backlog.copy():
            for cb in self._event_callbacks:
                cb(event)
            self._event_backlog.remove(event)

    def on_event(self, event: Event) -> None:
        if isinstance(event, Command):
            if event.cmd == Opt.DO:
                return self.handle_do(event.opt)
            elif event.cmd == Opt.DONT:
                return self.handle_dont(event.opt)
            elif event.cmd == Opt.WILL:
                return self.handle_will(event.opt)
            elif event.cmd == Opt.WONT:
                return self.handle_wont(event.opt)

    def check_local_option(self, option: Opt) -> bool:
        return self.options[option].local_option or False

    def check_remote_option(self, option: Opt) -> bool:
        return self.options[option].remote_option or False

    def handle_do(self, option: Opt) -> None:
        self.options[option].reply_pending = False

        if option == Opt.ECHO:
            # DE requests us to echo their input
            if not self.options[Opt.ECHO].local_option:
                self.options[Opt.ECHO].local_option = True
                self.send_event(Command(Opt.WILL, Opt.ECHO))

        elif option == Opt.BINARY:
            # DE requests us to receive BINARY
            if not self.options[Opt.BINARY].local_option:
                self.options[Opt.BINARY].local_option = True
                self.send_event(Command(Opt.WILL, Opt.BINARY))

        elif option == Opt.SGA:
            # DE wants us to suppress go-ahead
            if not self.options[Opt.SGA].local_option:
                self.options[Opt.SGA].local_option = True
                self.send_event(Command(Opt.WILL, Opt.SGA))
                self.send_event(Command(Opt.DO, Opt.SGA))

    def handle_dont(self, option: Opt) -> None:
        pass

    def handle_will(self, option: Opt) -> None:
        pass

    def handle_wont(self, option: Opt) -> None:
        pass

    def receive_data(self, data: bytes) -> None:
        """
        Receive data from a stream into the state machine.
        """
        for byte in data:
            try:
                self._state.send(byte)
            except StopIteration:
                self._state = self._next_state()
                next(self._state)  # prime

        if self._input_buffer:
            self._create_event(ReceiveMessage(self._input_buffer.copy()))
            self._input_buffer.clear()

        self._run_event_backlog()

    def send(self, data: bytes) -> None:
        """
        Send raw data to the stream.
        """
        self._create_event(SendData(bytearray(data)))
        self._run_event_backlog()

    def send_message(self, data: bytes) -> None:
        """
        Send a message (text) to the stream.
        """
        data = data.replace(bytes([Opt.IAC]), bytes([Opt.IAC, Opt.IAC]))
        return self.send(data)

    def send_event(self, event: Event) -> None:
        """
        Send an encoded event to the stream.
        """
        return self.send(event.as_bytes())

    def _state_data(self) -> StateCoroutine:
        while True:
            char = yield
            if char == Opt.IAC:
                self._next_state = self._state_iac
                return
            elif char != Opt.NULL:
                self._input_buffer.append(char)

    def _state_iac(self) -> StateCoroutine:
        self._next_state = self._state_data

        cmd = yield
        if cmd in self._iac_mbs:
            # These commands are 3-byte
            opt = yield
            self._create_event(Command(Opt(cmd), Opt(opt)))
        elif cmd == Opt.IAC:
            # escaped IAC
            self._input_buffer.append(Opt.IAC)
        elif cmd == Opt.SB:
            self._next_state = self._state_sb
        else:
            self._create_event(Command(Opt(cmd)))

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
                    self._create_event(SubCommand(cmd, buf[1:]))
                    break
                elif opt == Opt.IAC:
                    # escaped IAC
                    buf.append(Opt.IAC)
            else:
                buf.append(data)
