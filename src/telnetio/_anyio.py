from typing import Any, Optional

from anyio.abc import AnyByteStream, ByteStream

from ._machine import Command, Data, Error, SubCommand, TelnetClient, TelnetMachine, TelnetServer


class _AnyioTelnet(ByteStream):
    def __init__(self, stream: AnyByteStream) -> None:
        self._stream = stream
        self._machine = TelnetMachine()

    async def aclose(self) -> None:
        pass

    async def send_eof(self) -> None:
        await self._stream.send_eof()

    def handle_command(self, event: Command) -> None:
        pass

    def handle_subcommand(self, event: SubCommand) -> None:
        pass

    def handle_error(self, event: Error) -> None:
        pass

    async def receive(self, max_bytes: int = 4096) -> bytes:
        out_data = b""

        while not out_data:
            recv_data = await self._stream.receive()
            for event in self._machine.receive_data(recv_data):
                if isinstance(event, Data):
                    out_data += event.msg
                elif isinstance(event, Command):
                    self.handle_command(event)
                elif isinstance(event, SubCommand):
                    self.handle_subcommand(event)
                elif isinstance(event, Error):
                    self.handle_error(event)

        return out_data

    async def send(self, data: bytes) -> None:
        data = self._machine.send_message(data)
        await self._stream.send(data)

    async def send_command(self, cmd: int, opt: Optional[int] = None) -> None:
        data = self._machine.send_command(cmd, opt)
        await self._stream.send(data)


class AnyioTelnetServer(_AnyioTelnet):
    def __init__(self, stream: AnyByteStream, *args: Any, **kwargs: Any) -> None:
        super().__init__(stream, *args, **kwargs)
        self._server = TelnetServer(self._machine)


class AnyioTelnetClient(_AnyioTelnet):
    def __init__(self, stream: AnyByteStream, *args: Any, **kwargs: Any) -> None:
        super().__init__(stream, *args, **kwargs)
        self._client = TelnetClient(self._machine)
