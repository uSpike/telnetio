import math
import sys
from types import TracebackType
from typing import AsyncIterator, Optional, Type, TypeVar

import anyio
from anyio.abc import AnyByteStream, ByteStream, TaskGroup
from anyio.streams.buffered import BufferedByteReceiveStream

from ._machine import Event, TelnetClient, TelnetMachine, TelnetServer

if sys.version_info >= (3, 7):
    from contextlib import asynccontextmanager
else:
    from async_generator import asynccontextmanager

T = TypeVar("T", bound="_AnyioTelnet")


class _AnyioTelnet(ByteStream):
    _task_group: TaskGroup

    def __init__(self, stream: AnyByteStream) -> None:
        self._stream = stream
        msg_stream_producer, msg_stream_consumer = anyio.create_memory_object_stream(math.inf, item_type=bytes)
        self._msg_stream_buff = BufferedByteReceiveStream(msg_stream_consumer)
        send_producer, self._send_consumer = anyio.create_memory_object_stream(math.inf, item_type=bytes)

        self._machine = TelnetMachine()
        self._machine.register_event_cb(self._receive_event)
        self._machine.register_receive_cb(msg_stream_producer.send_nowait)
        self._machine.register_send_cb(send_producer.send_nowait)

    @asynccontextmanager
    async def _make_ctx(self: T) -> AsyncIterator[T]:
        async with anyio.create_task_group() as self._task_group:
            self._task_group.start_soon(self._receive_worker)
            self._task_group.start_soon(self._send_worker)
            try:
                yield self
            finally:
                self._task_group.cancel_scope.cancel()
                await self.aclose()

    async def __aenter__(self: T) -> T:
        self._ctx = self._make_ctx()
        return await self._ctx.__aenter__()

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        await self._ctx.__aexit__(exc_type, exc, tb)

    async def _receive_worker(self) -> None:
        async for data in self._stream:
            self._machine.receive_data(data)

    async def _send_worker(self) -> None:
        async for data in self._send_consumer:
            await self._stream.send(data)

    def _receive_event(self, event: Event) -> None:
        print("received event", event)

    async def aclose(self) -> None:
        await self._msg_stream_buff.aclose()

    async def send_eof(self) -> None:
        await self._stream.send_eof()

    async def receive(self, max_bytes: int = 4096) -> bytes:
        return await self._msg_stream_buff.receive(max_bytes=max_bytes)

    async def send(self, data: bytes) -> None:
        self._machine.send_message(data)


class AnyioTelnetServer(_AnyioTelnet):
    def __init__(self, stream: AnyByteStream) -> None:
        super().__init__(stream)
        self._server = TelnetServer(self._machine)


class AnyioTelnetClient(_AnyioTelnet):
    def __init__(self, stream: AnyByteStream) -> None:
        super().__init__(stream)
        self._client = TelnetClient(self._machine)
