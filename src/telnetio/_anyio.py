from typing import List, Type, TypeVar

import anyio
from anyio.abc import AnyByteStream, ByteStream
from anyio.streams.buffered import BufferedByteReceiveStream

from ._machine import Data, Event, TelnetMachine

ET = TypeVar("ET", bound=Event)


class AnyioTelnetServer(ByteStream):
    def __init__(self, stream: AnyByteStream) -> None:
        self._stream_send = stream
        self._stream_receive = BufferedByteReceiveStream(stream)
        self._machine = TelnetMachine()
        self._events: List[Event] = []

    async def __aenter__(self) -> "AnyioTelnetServer":
        await self._begin_negotiation()
        return self

    async def aclose(self) -> None:
        await self._stream_receive.aclose()

    async def send_eof(self) -> None:
        pass

    async def _begin_negotiation(self) -> None:
        pass

    async def receive(self, max_bytes: int = 4096) -> bytes:
        data = await self._receive_event(event_type=Data, max_bytes=max_bytes)
        return bytes(data.contents)

    async def _receive_event(self, event_type: Type[ET] = Event, max_bytes: int = 4096) -> ET:  # type: ignore[assignment]  # https://github.com/python/mypy/issues/3737
        while True:
            for idx, event in enumerate(self._events):
                if isinstance(event, event_type):
                    self._events.pop(idx)
                    return event
            data = await self._stream_receive.receive(max_bytes=max_bytes)
            for event in self._machine.receive_data(data):
                self._events.append(event)

    async def send(self, data: bytes) -> None:
        data = self._machine.send(data)
        await self._stream_send.send(data)


if __name__ == "__main__":
    # simple telnet echo server
    async def handler(stream: AnyByteStream) -> None:
        async with AnyioTelnetServer(stream) as telnet:
            async for data in telnet:
                await telnet.send(data)

    async def main() -> None:
        listener = await anyio.create_tcp_listener(local_port=1234)
        await listener.serve(handler)

    anyio.run(main)
